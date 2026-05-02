"""Analytics LLM backends (Ollama, OpenAI-compatible, Anthropic, Gemini) over httpx."""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

import logging

import httpx
from youtube_scrape.adapters.llm_chat_types import LlmChatResult
from youtube_scrape.adapters.llm_errors import LlmTransportError
from youtube_scrape.adapters.llm_usage_extract import anthropic_usage_counts, gemini_usage_counts, openai_compat_usage_counts
from youtube_scrape.adapters.ollama_client import (
    ensure_ollama_ready,
    ollama_chat_messages,
    ollama_list_model_names,
)
from youtube_scrape.settings import AnalyticsLlmProvider, Settings

log = logging.getLogger(__name__)


def _join_url(base: str, suffix: str) -> str:
    return base.rstrip("/") + "/" + suffix.lstrip("/")


def _text_detail(resp: httpx.Response, head: int = 800) -> str:
    body = (resp.text or "").strip()
    return body[:head] if body else f"HTTP {resp.status_code}"


def _openai_headers(settings: Settings) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    key = settings.openai_compatible_api_key.strip()
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


@runtime_checkable
class AnalyticsLlmBackend(Protocol):
    async def ensure_ready(self, *, timeout_s: float) -> None: ...

    async def chat(
        self,
        *,
        system: str | None,
        user: str,
        json_format: bool,
        timeout_s: float,
        log_context: str,
    ) -> str: ...

    async def chat_messages(
        self,
        *,
        system: str | None,
        messages: list[dict[str, str]],
        json_format: bool,
        timeout_s: float,
        log_context: str,
    ) -> LlmChatResult: ...

    async def probe(self, *, timeout_s: float = 12.0) -> tuple[bool, str, list[str] | None]: ...


class OllamaAnalyticsBackend:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    async def ensure_ready(self, *, timeout_s: float) -> None:
        await ensure_ollama_ready(
            base_url=self._s.ollama_base_url,
            model=self._s.ollama_model,
            timeout_s=timeout_s,
        )

    async def chat(
        self,
        *,
        system: str | None,
        user: str,
        json_format: bool,
        timeout_s: float,
        log_context: str,
    ) -> str:
        result = await self.chat_messages(
            system=system,
            messages=[{"role": "user", "content": user}],
            json_format=json_format,
            timeout_s=timeout_s,
            log_context=log_context,
        )
        return result.content

    async def chat_messages(
        self,
        *,
        system: str | None,
        messages: list[dict[str, str]],
        json_format: bool,
        timeout_s: float,
        log_context: str,
    ) -> LlmChatResult:
        ollama_msgs: list[dict[str, str]] = []
        if system and system.strip():
            ollama_msgs.append({"role": "system", "content": system.strip()})
        ollama_msgs.extend(messages)
        return await ollama_chat_messages(
            base_url=self._s.ollama_base_url,
            model=self._s.ollama_model,
            messages=ollama_msgs,
            json_format=json_format,
            timeout_s=timeout_s,
            log_context=log_context,
        )

    async def probe(self, *, timeout_s: float = 12.0) -> tuple[bool, str, list[str] | None]:
        names = await ollama_list_model_names(base_url=self._s.ollama_base_url, timeout_s=timeout_s)
        if not names:
            return False, "Ollama responded but reported no pulled models.", None
        return True, f"Reachable — {len(names)} model(s) on daemon.", names[:24]


class OpenAiCompatibleBackend:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    async def ensure_ready(self, *, timeout_s: float) -> None:
        ok, msg, _ = await self.probe(timeout_s=min(timeout_s, 15.0))
        if not ok:
            raise LlmTransportError(msg)

    async def chat(
        self,
        *,
        system: str | None,
        user: str,
        json_format: bool,
        timeout_s: float,
        log_context: str,
    ) -> str:
        result = await self.chat_messages(
            system=system,
            messages=[{"role": "user", "content": user}],
            json_format=json_format,
            timeout_s=timeout_s,
            log_context=log_context,
        )
        return result.content

    async def chat_messages(
        self,
        *,
        system: str | None,
        messages: list[dict[str, str]],
        json_format: bool,
        timeout_s: float,
        log_context: str,
    ) -> LlmChatResult:
        base = self._s.openai_compatible_base_url.rstrip("/")
        url = _join_url(base, "chat/completions")
        api_messages: list[dict[str, str]] = []
        if system and system.strip():
            api_messages.append({"role": "system", "content": system.strip()})
        api_messages.extend(messages)
        payload: dict[str, Any] = {
            "model": self._s.openai_compatible_model,
            "messages": api_messages,
        }
        if json_format:
            payload["response_format"] = {"type": "json_object"}
        t = httpx.Timeout(timeout_s, connect=min(15.0, timeout_s))
        headers = _openai_headers(self._s)
        async with httpx.AsyncClient(timeout=t) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if json_format and resp.status_code >= 400:
                err_txt = _text_detail(resp, 400)
                if "response_format" in err_txt or resp.status_code == 400:
                    log.info(
                        "openai_compat_retry_without_json_object",
                        extra={"context": log_context, "status": resp.status_code},
                    )
                    payload.pop("response_format", None)
                    resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                raise LlmTransportError(f"OpenAI-compatible HTTP {resp.status_code}: {_text_detail(resp)}")
            try:
                body = resp.json()
            except ValueError as exc:
                raise LlmTransportError("OpenAI-compatible response was not JSON") from exc
        text = _openai_extract_assistant_text(body)
        pt, ct, tt = openai_compat_usage_counts(body)
        return LlmChatResult(content=text, prompt_tokens=pt, completion_tokens=ct, total_tokens=tt)

    async def probe(self, *, timeout_s: float = 12.0) -> tuple[bool, str, list[str] | None]:
        base = self._s.openai_compatible_base_url.rstrip("/")
        url = _join_url(base, "models")
        t = httpx.Timeout(timeout_s, connect=min(10.0, timeout_s))
        headers = _openai_headers(self._s)
        async with httpx.AsyncClient(timeout=t) as client:
            try:
                resp = await client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                return False, f"Cannot reach OpenAI-compatible API: {exc}", None
        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError:
                return True, "Reachable (models list was not JSON).", None
            models = data.get("data") if isinstance(data, dict) else None
            names: list[str] = []
            if isinstance(models, list):
                for m in models:
                    if isinstance(m, dict):
                        mid = m.get("id")
                        if isinstance(mid, str) and mid.strip():
                            names.append(mid.strip())
            return True, "Reachable via GET /v1/models.", names[:24] if names else None
        if resp.status_code in (401, 403):
            return False, f"Auth failed ({resp.status_code}): {_text_detail(resp, 400)}", None
        # Minimal chat fallback (some gateways omit /models)
        try:
            await self.chat(
                system=None,
                user="Reply with exactly the word: ok",
                json_format=False,
                timeout_s=min(timeout_s, 20.0),
                log_context="llm_probe_compat",
            )
        except LlmTransportError as exc:
            return False, str(exc), None
        return True, "Reachable (chat/completions smoke ok; /models unavailable).", None


def _openai_extract_assistant_text(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LlmTransportError("OpenAI-compatible response missing choices")
    ch0 = choices[0]
    if not isinstance(ch0, dict):
        raise LlmTransportError("OpenAI-compatible choice is not an object")
    msg = ch0.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for p in content:
                if isinstance(p, dict) and isinstance(p.get("text"), str):
                    parts.append(p["text"])
            joined = "\n".join(parts).strip()
            if joined:
                return joined
    raise LlmTransportError("OpenAI-compatible response had no assistant text")


class AnthropicBackend:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    async def ensure_ready(self, *, timeout_s: float) -> None:
        if not self._s.anthropic_api_key.strip():
            raise LlmTransportError("Anthropic selected but YOUTUBE_SCRAPE_ANTHROPIC_API_KEY is empty.")
        ok, msg, _ = await self.probe(timeout_s=min(timeout_s, 15.0))
        if not ok:
            raise LlmTransportError(msg)

    async def chat(
        self,
        *,
        system: str | None,
        user: str,
        json_format: bool,
        timeout_s: float,
        log_context: str,
    ) -> str:
        result = await self.chat_messages(
            system=system,
            messages=[{"role": "user", "content": user}],
            json_format=json_format,
            timeout_s=timeout_s,
            log_context=log_context,
        )
        return result.content

    async def chat_messages(
        self,
        *,
        system: str | None,
        messages: list[dict[str, str]],
        json_format: bool,
        timeout_s: float,
        log_context: str,
    ) -> LlmChatResult:
        _ = json_format, log_context
        base = self._s.anthropic_base_url.rstrip("/")
        url = _join_url(base, "v1/messages")
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._s.anthropic_api_key.strip(),
            "anthropic-version": "2023-06-01",
        }
        anth_msgs: list[dict[str, str]] = [{"role": m["role"], "content": m["content"]} for m in messages]
        if anth_msgs and anth_msgs[0]["role"] != "user":
            anth_msgs.insert(0, {"role": "user", "content": "(Begin.)"})
        payload: dict[str, Any] = {
            "model": self._s.anthropic_model,
            "max_tokens": 8192,
            "messages": anth_msgs,
        }
        if system and system.strip():
            payload["system"] = system.strip()
        t = httpx.Timeout(timeout_s, connect=min(15.0, timeout_s))
        async with httpx.AsyncClient(timeout=t) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise LlmTransportError(f"Anthropic HTTP {resp.status_code}: {_text_detail(resp)}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise LlmTransportError("Anthropic response was not JSON") from exc
        text_a = _anthropic_extract_text(body)
        pt, ct, tt = anthropic_usage_counts(body)
        return LlmChatResult(content=text_a, prompt_tokens=pt, completion_tokens=ct, total_tokens=tt)

    async def probe(self, *, timeout_s: float = 12.0) -> tuple[bool, str, list[str] | None]:
        if not self._s.anthropic_api_key.strip():
            return False, "Missing Anthropic API key.", None
        base = self._s.anthropic_base_url.rstrip("/")
        list_url = _join_url(base, "v1/models")
        t = httpx.Timeout(timeout_s, connect=min(10.0, timeout_s))
        headers = {
            "x-api-key": self._s.anthropic_api_key.strip(),
            "anthropic-version": "2023-06-01",
        }
        async with httpx.AsyncClient(timeout=t) as client:
            resp = await client.get(list_url, headers=headers)
        if resp.status_code == 200:
            names: list[str] = []
            try:
                data = resp.json()
                arr = data.get("data") if isinstance(data, dict) else None
                if isinstance(arr, list):
                    for m in arr:
                        if isinstance(m, dict) and isinstance(m.get("id"), str):
                            names.append(m["id"].strip())
            except ValueError:
                pass
            return True, "Reachable — Anthropic /v1/models ok.", names[:24] if names else None
        if resp.status_code in (401, 403):
            return False, f"Anthropic auth failed ({resp.status_code}): {_text_detail(resp, 400)}", None
        try:
            await self.chat(
                system=None,
                user="Reply with the single word: ok",
                json_format=False,
                timeout_s=min(timeout_s, 15.0),
                log_context="llm_probe_anthropic",
            )
            return True, "Reachable — messages smoke ok (models list unavailable).", None
        except LlmTransportError as exc:
            return False, str(exc), None


def _anthropic_extract_text(body: dict[str, Any]) -> str:
    content = body.get("content")
    if not isinstance(content, list):
        raise LlmTransportError("Anthropic response missing content")
    texts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            t = block.get("text")
            if isinstance(t, str) and t.strip():
                texts.append(t.strip())
    out = "\n".join(texts).strip()
    if not out:
        raise LlmTransportError("Anthropic returned no text blocks")
    return out


class GeminiBackend:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def _endpoint(self, action: Literal["generateContent", "models"]) -> str:
        key = self._s.google_gemini_api_key.strip()
        mid = self._s.google_gemini_model.strip()
        root = "https://generativelanguage.googleapis.com/v1beta"
        if action == "generateContent":
            q = f"?key={key}" if key else ""
            return f"{root}/models/{mid}:generateContent{q}"
        q = f"?key={key}" if key else ""
        return f"{root}/models{q}"

    async def ensure_ready(self, *, timeout_s: float) -> None:
        if not self._s.google_gemini_api_key.strip():
            raise LlmTransportError("Gemini selected but YOUTUBE_SCRAPE_GOOGLE_GEMINI_API_KEY is empty.")
        ok, msg, _ = await self.probe(timeout_s=min(timeout_s, 15.0))
        if not ok:
            raise LlmTransportError(msg)

    async def chat(
        self,
        *,
        system: str | None,
        user: str,
        json_format: bool,
        timeout_s: float,
        log_context: str,
    ) -> str:
        result = await self.chat_messages(
            system=system,
            messages=[{"role": "user", "content": user}],
            json_format=json_format,
            timeout_s=timeout_s,
            log_context=log_context,
        )
        return result.content

    async def chat_messages(
        self,
        *,
        system: str | None,
        messages: list[dict[str, str]],
        json_format: bool,
        timeout_s: float,
        log_context: str,
    ) -> LlmChatResult:
        _ = log_context
        url = self._endpoint("generateContent")
        contents: list[dict[str, Any]] = []
        for m in messages:
            r = "user" if m["role"] == "user" else "model"
            contents.append({"role": r, "parts": [{"text": m["content"]}]})
        body: dict[str, Any] = {"contents": contents}
        if system and system.strip():
            body["systemInstruction"] = {"parts": [{"text": system.strip()}]}
        if json_format:
            body["generationConfig"] = {"responseMimeType": "application/json"}
        t = httpx.Timeout(timeout_s, connect=min(15.0, timeout_s))
        async with httpx.AsyncClient(timeout=t) as client:
            resp = await client.post(url, json=body)
        if resp.status_code >= 400:
            raise LlmTransportError(f"Gemini HTTP {resp.status_code}: {_text_detail(resp)}")
        try:
            parsed = resp.json()
        except ValueError as exc:
            raise LlmTransportError("Gemini response was not JSON") from exc
        gem_text = _gemini_extract_text(parsed)
        pt, ct, tt = gemini_usage_counts(parsed)
        return LlmChatResult(content=gem_text, prompt_tokens=pt, completion_tokens=ct, total_tokens=tt)

    async def probe(self, *, timeout_s: float = 12.0) -> tuple[bool, str, list[str] | None]:
        if not self._s.google_gemini_api_key.strip():
            return False, "Missing Google Gemini API key.", None
        url = self._endpoint("models")
        t = httpx.Timeout(timeout_s, connect=min(10.0, timeout_s))
        async with httpx.AsyncClient(timeout=t) as client:
            resp = await client.get(url)
        if resp.status_code >= 400:
            return False, f"Gemini HTTP {resp.status_code}: {_text_detail(resp)}", None
        names: list[str] = []
        try:
            data = resp.json()
            models = data.get("models") if isinstance(data, dict) else None
            if isinstance(models, list):
                for m in models:
                    if isinstance(m, dict) and isinstance(m.get("name"), str):
                        n = m["name"].replace("models/", "").strip()
                        if n:
                            names.append(n)
        except ValueError:
            pass
        return True, "Reachable — Gemini model list OK.", names[:24] if names else None


def _gemini_extract_text(body: dict[str, Any]) -> str:
    cands = body.get("candidates")
    if not isinstance(cands, list) or not cands:
        raise LlmTransportError("Gemini response missing candidates")
    c0 = cands[0]
    if not isinstance(c0, dict):
        raise LlmTransportError("Gemini candidate not an object")
    content = c0.get("content")
    if not isinstance(content, dict):
        raise LlmTransportError("Gemini candidate missing content")
    parts = content.get("parts")
    if not isinstance(parts, list):
        raise LlmTransportError("Gemini content missing parts")
    texts: list[str] = []
    for p in parts:
        if isinstance(p, dict) and isinstance(p.get("text"), str):
            texts.append(p["text"])
    out = "\n".join(texts).strip()
    if not out:
        raise LlmTransportError("Gemini returned empty text")
    return out


def build_analytics_llm(settings: Settings) -> AnalyticsLlmBackend:
    """Construct the configured analytics LLM backend."""

    p: AnalyticsLlmProvider = settings.analytics_llm_provider
    if p == "ollama":
        return OllamaAnalyticsBackend(settings)
    if p == "openai_compatible":
        return OpenAiCompatibleBackend(settings)
    if p == "anthropic":
        return AnthropicBackend(settings)
    if p == "google_gemini":
        return GeminiBackend(settings)
    raise LlmTransportError(f"Unknown analytics_llm_provider: {p!r}")


async def probe_analytics_llm(settings: Settings) -> dict[str, Any]:
    """Run provider connectivity check; returns a dict for ``AnalyticsLlmProbePayload``."""

    if not settings.analytics_ollama_enabled:
        return {
            "ok": False,
            "provider": settings.analytics_llm_provider,
            "message": "LLM analytics disabled (YOUTUBE_SCRAPE_ANALYTICS_OLLAMA_ENABLED=false).",
            "models_sample": None,
        }
    backend = build_analytics_llm(settings)
    ok, message, sample = await backend.probe(timeout_s=12.0)
    return {
        "ok": ok,
        "provider": settings.analytics_llm_provider,
        "message": message,
        "models_sample": sample,
    }
