"""HTTP client for local Ollama (optional analytics synthesis)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from youtube_scrape.adapters.llm_errors import LlmTransportError

log = logging.getLogger(__name__)


class OllamaHttpError(LlmTransportError):
    """Raised when Ollama returns a non-success HTTP status or empty body."""


def normalize_ollama_base_url(raw: str) -> str:
    """Strip trailing slashes and prepend ``http://`` when scheme is omitted (httpx rejects host:port-only)."""

    base = raw.strip().rstrip("/")
    if not base:
        return base
    low = base.lower()
    if low.startswith("http://") or low.startswith("https://"):
        return base
    return f"http://{base}"


def _ollama_error_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, str) and err.strip():
                return err.strip()
    except ValueError:
        pass
    return (resp.text or "").strip()[:800]


def _coerce_text_field(value: Any) -> str:
    """Normalize ``content`` / ``thinking`` which may be str or structured JSON from some models."""

    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict):
                t = item.get("text")
                if isinstance(t, str):
                    chunks.append(t)
                elif isinstance(item.get("content"), str):
                    chunks.append(item["content"])
        joined = "\n".join(chunks).strip()
        if joined:
            return joined
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
            if isinstance(inner, dict):
                nested = inner.get("text")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
                nc = inner.get("content")
                if isinstance(nc, str) and nc.strip():
                    return nc.strip()
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value).strip()
    return str(value).strip()


def _think_request_field(model: str) -> bool | str:
    """Enable separate ``thinking`` traces when models emit JSON there (e.g. GPT-OSS needs a level string)."""

    lower = model.strip().lower()
    if "gpt-oss" in lower:
        return "low"
    return True


def _macro_json_likelihood(text: str) -> int:
    """Score which assistant field probably holds the structured analytics JSON."""

    if not text.strip():
        return 0
    s = text
    score = 0
    if '"themes"' in s or "'themes'" in s:
        score += 6
    if "sentiment_overview" in s:
        score += 4
    if "suggestions_and_requests" in s:
        score += 2
    if s.strip().startswith("{") and "}" in s:
        score += 2
    # Thinking models (e.g. gpt-oss) often leave ``content`` as "{}" and put JSON in ``thinking``.
    if s.strip() in ("{}", "[]"):
        score -= 10
    if len(s.strip()) > 80:
        score += 1
    return score


def _summarize_chat_response(body: dict[str, Any], *, head: int = 160) -> dict[str, Any]:
    """Safe diagnostic snapshot (no huge blobs)."""

    out: dict[str, Any] = {"top_level_keys": sorted(body.keys())}
    msg = body.get("message")
    if isinstance(msg, dict):
        out["message_keys"] = sorted(msg.keys())
        for key in ("role", "content", "thinking", "reasoning"):
            raw = msg.get(key)
            coerced = _coerce_text_field(raw)
            out[f"{key}_type"] = type(raw).__name__
            out[f"{key}_chars"] = len(coerced)
            if coerced:
                one_line = coerced.replace("\n", "\\n")[:head]
                out[f"{key}_head"] = one_line
    elif msg is not None:
        out["message_type"] = type(msg).__name__
    if "model" in body:
        out["response_model"] = body.get("model")
    if "done" in body:
        out["done"] = body.get("done")
    return out


def extract_assistant_text(body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return assistant text plus extraction diagnostics for logging."""

    meta: dict[str, Any] = {"top_level_keys": sorted(body.keys())}
    msg = body.get("message")
    if isinstance(msg, dict):
        content = _coerce_text_field(msg.get("content"))
        thinking = _coerce_text_field(msg.get("thinking"))
        reasoning = _coerce_text_field(msg.get("reasoning"))
        meta["content_chars"] = len(content)
        meta["thinking_chars"] = len(thinking)
        meta["reasoning_chars"] = len(reasoning)
        tc = _macro_json_likelihood(content)
        tk = _macro_json_likelihood(thinking)
        tr = _macro_json_likelihood(reasoning)
        meta["content_json_score"] = tc
        meta["thinking_json_score"] = tk
        meta["reasoning_json_score"] = tr

        # Prefer the field most likely to hold macro JSON; on ties, prefer official ``content``.
        tie_order = {"content": 0, "thinking": 1, "reasoning": 2}
        candidates: list[tuple[str, str, int]] = [
            ("content", content, tc),
            ("thinking", thinking, tk),
            ("reasoning", reasoning, tr),
        ]
        nonempty = [(name, text, score) for name, text, score in candidates if text.strip()]
        if nonempty:
            nonempty.sort(key=lambda x: (-x[2], tie_order[x[0]]))
            picked_name, picked_text, _score = nonempty[0]
            meta["picked"] = picked_name
            return picked_text, meta

    if isinstance(msg, str) and msg.strip():
        meta["picked"] = "message_flat_str"
        return msg.strip(), meta

    r = body.get("response")
    if isinstance(r, str) and r.strip():
        meta["picked"] = "legacy_response_field"
        return r.strip(), meta

    meta["picked"] = "none"
    return "", meta


def _extract_chat_content(body: dict[str, Any]) -> str:
    """Backward-compatible: assistant text only."""

    text, _ = extract_assistant_text(body)
    return text


def model_matches_installed(requested: str, installed_names: list[str]) -> bool:
    """True if ``requested`` matches an Ollama tag list entry (e.g. ``llama3`` vs ``llama3:latest``)."""

    req = requested.strip().lower()
    if not req:
        return False
    req_base = req.split(":", 1)[0]
    for name in installed_names:
        nl = name.strip().lower()
        if nl == req:
            return True
        inst_base = nl.split(":", 1)[0]
        if inst_base == req_base:
            return True
        if nl.startswith(req + ":"):
            return True
    return False


async def ollama_list_model_names(*, base_url: str, timeout_s: float = 8.0) -> list[str]:
    """GET ``/api/tags`` and return model ``name`` fields."""

    normalized = normalize_ollama_base_url(base_url)
    url = normalized.rstrip("/") + "/api/tags"
    t = httpx.Timeout(timeout_s, connect=min(10.0, timeout_s))
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=t) as client:
        try:
            resp = await client.get(url)
        except httpx.ConnectError as exc:
            log.warning(
                "ollama_tags_connect_error",
                extra={"url": url, "elapsed_ms": round((time.monotonic() - t0) * 1000)},
            )
            raise OllamaHttpError(
                f"Cannot connect to Ollama at {normalized.rstrip('/')}. "
                "Is the daemon running? Try `ollama serve` or open the Ollama app. "
                "If Ollama listens elsewhere, set YOUTUBE_SCRAPE_OLLAMA_BASE_URL."
            ) from exc
        except httpx.HTTPError as exc:
            log.warning(
                "ollama_tags_http_error",
                extra={"error": str(exc), "elapsed_ms": round((time.monotonic() - t0) * 1000)},
            )
            raise OllamaHttpError(f"Ollama tags request failed: {exc}") from exc

    elapsed_ms = round((time.monotonic() - t0) * 1000)
    if resp.status_code >= 400:
        detail = _ollama_error_detail(resp)
        log.warning(
            "ollama_tags_http_status",
            extra={"status": resp.status_code, "detail": detail[:400], "elapsed_ms": elapsed_ms},
        )
        raise OllamaHttpError(f"Ollama HTTP {resp.status_code} on /api/tags: {detail}")

    try:
        data = resp.json()
    except ValueError as exc:
        log.warning("ollama_tags_json_error", extra={"elapsed_ms": elapsed_ms})
        raise OllamaHttpError("Ollama /api/tags response was not JSON") from exc

    models = data.get("models")
    if not isinstance(models, list):
        log.info("ollama_tags_ok", extra={"model_count": 0, "elapsed_ms": elapsed_ms})
        return []

    names: list[str] = []
    for m in models:
        if isinstance(m, dict):
            n = m.get("name")
            if isinstance(n, str) and n.strip():
                names.append(n.strip())
    log.info(
        "ollama_tags_ok",
        extra={"model_count": len(names), "elapsed_ms": elapsed_ms, "sample": names[:5]},
    )
    return names


async def ensure_ollama_ready(*, base_url: str, model: str, timeout_s: float = 10.0) -> None:
    """Verify daemon is reachable and the configured model exists locally."""

    root = normalize_ollama_base_url(base_url)
    names = await ollama_list_model_names(base_url=root, timeout_s=timeout_s)
    if not names:
        log.warning("ollama_ready_no_models", extra={"base_url": root})
        raise OllamaHttpError(
            f"Ollama at {root.rstrip('/')} reports no models. Pull one first, e.g. `ollama pull {model}`."
        )
    if model_matches_installed(model, names):
        log.info(
            "ollama_ready_model_ok",
            extra={"requested_model": model, "installed_count": len(names)},
        )
        return
    preview = ", ".join(names[:16])
    suffix = " …" if len(names) > 16 else ""
    log.warning(
        "ollama_ready_model_missing",
        extra={"requested_model": model, "installed_sample": names[:8]},
    )
    raise OllamaHttpError(
        f'Model "{model}" is not available locally. Installed: {preview}{suffix}. '
        f'Set YOUTUBE_SCRAPE_OLLAMA_MODEL to one of these names or run `ollama pull {model}`.'
    )


async def ollama_chat_message(
    *,
    base_url: str,
    model: str,
    user_content: str,
    system_content: str | None = None,
    timeout_s: float,
    json_format: bool = True,
    log_context: str | None = None,
) -> str:
    """POST ``/api/chat`` and return assistant message content (non-streaming)."""

    root = normalize_ollama_base_url(base_url)
    url = root.rstrip("/") + "/api/chat"
    msgs: list[dict[str, str]] = []
    if system_content and system_content.strip():
        msgs.append({"role": "system", "content": system_content.strip()})
    msgs.append({"role": "user", "content": user_content})
    base_payload: dict[str, Any] = {
        "model": model,
        "messages": msgs,
        "stream": False,
        # Thinking-capable models often place structured JSON in ``message.thinking``; GPT-OSS ignores boolean
        # ``think`` and expects low/medium/high.
        "think": _think_request_field(model),
    }

    payloads: list[dict[str, Any]] = []
    if json_format:
        payloads.append({**base_payload, "format": "json"})
    payloads.append(base_payload)

    t = httpx.Timeout(timeout_s, connect=min(15.0, timeout_s))
    ctx = log_context or "ollama_chat"
    async with httpx.AsyncClient(timeout=t) as client:
        last_detail = ""
        for i, payload in enumerate(payloads):
            attempt_label = f"{i + 1}/{len(payloads)}"
            uses_json_format = payload.get("format") == "json"
            t0 = time.monotonic()
            try:
                resp = await client.post(url, json=payload)
            except httpx.ConnectError as exc:
                log.warning(
                    f"{ctx}_connect_error",
                    extra={
                        "attempt": attempt_label,
                        "json_format": uses_json_format,
                        "elapsed_ms": round((time.monotonic() - t0) * 1000),
                    },
                )
                raise OllamaHttpError(
                    f"Cannot connect to Ollama at {root.rstrip('/')}. "
                    "Start Ollama or set YOUTUBE_SCRAPE_OLLAMA_BASE_URL."
                ) from exc
            except httpx.HTTPError as exc:
                log.warning(
                    f"{ctx}_http_transport_error",
                    extra={
                        "attempt": attempt_label,
                        "error": str(exc),
                        "elapsed_ms": round((time.monotonic() - t0) * 1000),
                    },
                )
                raise OllamaHttpError(f"Ollama request failed: {exc}") from exc

            elapsed_ms = round((time.monotonic() - t0) * 1000)

            if resp.status_code < 400:
                try:
                    body = resp.json()
                except ValueError as exc:
                    log.error(
                        f"{ctx}_response_not_json",
                        extra={"attempt": attempt_label, "elapsed_ms": elapsed_ms},
                    )
                    raise OllamaHttpError("Ollama response was not JSON") from exc

                if not isinstance(body, dict):
                    log.error(f"{ctx}_response_not_object", extra={"attempt": attempt_label})
                    raise OllamaHttpError("Ollama response JSON was not an object")

                text, ext_meta = extract_assistant_text(body)
                summary = _summarize_chat_response(body)
                if text:
                    log.info(
                        f"{ctx}_ok",
                        extra={
                            "attempt": attempt_label,
                            "json_format": uses_json_format,
                            "http_status": resp.status_code,
                            "elapsed_ms": elapsed_ms,
                            "assistant_chars": len(text),
                            **ext_meta,
                        },
                    )
                    log.debug(f"{ctx}_body_summary", extra=summary)
                    return text

                log.error(
                    f"{ctx}_empty_assistant_after_success",
                    extra={
                        "attempt": attempt_label,
                        "json_format": uses_json_format,
                        "elapsed_ms": elapsed_ms,
                        **summary,
                    },
                )
                raise OllamaHttpError(
                    "Ollama returned success but no assistant text in message.content / thinking "
                    "(see API stderr logs for message_*_keys). Check model compatibility."
                )

            last_detail = _ollama_error_detail(resp)
            log.warning(
                f"{ctx}_http_error_status",
                extra={
                    "attempt": attempt_label,
                    "json_format": uses_json_format,
                    "http_status": resp.status_code,
                    "detail": last_detail[:500],
                    "elapsed_ms": elapsed_ms,
                },
            )

            # Older daemons may reject ``format``; retry plain chat once.
            if (
                json_format
                and i == 0
                and resp.status_code == 400
                and len(payloads) > 1
            ):
                log.info(
                    "ollama_retry_chat_without_json_format",
                    extra={"detail": last_detail[:240]},
                )
                continue

            raise OllamaHttpError(f"Ollama HTTP {resp.status_code}: {last_detail}")
