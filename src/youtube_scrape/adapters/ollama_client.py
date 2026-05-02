"""HTTP client for local Ollama (optional analytics synthesis)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from youtube_scrape.adapters.llm_chat_types import LlmChatResult
from youtube_scrape.adapters.llm_errors import LlmTransportError
from youtube_scrape.adapters.llm_usage_extract import ollama_chat_usage_counts

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


def _coerce_embedding_numbers(raw: list[Any]) -> list[float]:
    """Validate and normalize one embedding vector."""

    out: list[float] = []
    for x in raw:
        if isinstance(x, bool):
            raise OllamaHttpError("Ollama embedding contained boolean values")
        if isinstance(x, int | float):
            out.append(float(x))
        else:
            raise OllamaHttpError("Ollama embedding contained non-numeric values")
    return out


def _looks_like_ollama_model_pull_missing(detail_lower: str) -> bool:
    """True when the error is specifically 'model not pulled' (don't waste CPU-retries).

    Distinguished from GPU load failures ('model exists but failed to load').
    """

    return "pull" in detail_lower and ("not found" in detail_lower or "does not exist" in detail_lower)


def _embedding_should_retry_cpu(*, http_status: int, detail_lower: str) -> bool:
    """True when a CPU-only load may succeed (large chat models often saturate GPU VRAM)."""

    if _looks_like_ollama_model_pull_missing(detail_lower):
        return False
    if http_status >= 500:
        return True
    return any(
        needle in detail_lower
        for needle in (
            "failed to load",
            "unable to load",
            "could not load model",
            "out of memory",
            "cuda error",
            "resource",
            "runner process has terminated",
            "runner process exited",
        )
    )


async def _ollama_post_embedding_json(
    *,
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
) -> tuple[int, dict[str, Any] | None, str]:
    """POST JSON to an embedding endpoint; return ``http_status``, parsed body (if dict), ``detail_raw``."""

    resp = await client.post(url, json=payload)
    detail_raw = _ollama_error_detail(resp).strip() if resp.status_code >= 400 else ""
    parsed: dict[str, Any] | None = None
    try:
        body = resp.json()
        if isinstance(body, dict):
            parsed = body
            if resp.status_code >= 400 and not detail_raw.strip():
                err = body.get("error")
                if isinstance(err, str) and err.strip():
                    detail_raw = err.strip()
    except ValueError:
        pass
    return resp.status_code, parsed, detail_raw


def _vector_from_embed_api_json(data: dict[str, Any]) -> list[float] | None:
    embs = data.get("embeddings")
    if not isinstance(embs, list) or not embs:
        return None
    first = embs[0]
    if not isinstance(first, list) or not first:
        return None
    return _coerce_embedding_numbers(first)


def _vector_from_legacy_embeddings_json(data: dict[str, Any]) -> list[float] | None:
    emb = data.get("embedding")
    if not isinstance(emb, list) or not emb:
        return None
    return _coerce_embedding_numbers(emb)


async def ollama_embed_prompt(
    *,
    base_url: str,
    model: str,
    prompt: str,
    timeout_s: float,
    client: httpx.AsyncClient | None = None,
) -> list[float]:
    """Request an embedding from Ollama.

    Prefers modern ``POST /api/embed`` (``input`` field). Falls back to legacy ``POST /api/embeddings``
    (``prompt`` field) for older daemons. When the model exists but fails to load on GPU (common if a
    large chat model is already resident), retries with ``options.num_gpu=0`` so embedding can run on CPU.
    """

    normalized = normalize_ollama_base_url(base_url)
    root = normalized.rstrip("/")
    url_embed = root + "/api/embed"
    url_legacy = root + "/api/embeddings"
    t = httpx.Timeout(timeout_s, connect=min(10.0, timeout_s))
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=t)
    assert client is not None

    diag: list[str] = []

    async def embed_round(url: str, *, modern: bool) -> list[float] | None:
        """Try ``/api/embed`` or legacy ``/api/embeddings``: GPU-first, CPU retry on plausible VRAM clashes."""

        for use_cpu in (False, True):
            if modern:
                payload: dict[str, Any] = {"model": model, "input": prompt, "truncate": True}
            else:
                payload = {"model": model, "prompt": prompt}
            if use_cpu:
                payload["options"] = {"num_gpu": 0}
            status, data, detail_raw = await _ollama_post_embedding_json(client=client, url=url, payload=payload)
            detail_lower = detail_raw.lower()

            if status < 400 and isinstance(data, dict):
                parsed = (
                    _vector_from_embed_api_json(data)
                    if modern
                    else _vector_from_legacy_embeddings_json(data)
                )
                if parsed:
                    if use_cpu:
                        log.info(
                            "ollama_embed_cpu_fallback_ok",
                            extra={
                                "endpoint": "/api/embed" if modern else "/api/embeddings",
                                "model_requested": model,
                            },
                        )
                    return parsed
                tail = detail_raw.strip() if detail_raw else "JSON parsed but embeddings empty"
                diag.append(f"{url} ({'CPU' if use_cpu else 'GPU'}) OK but unusable embedding: {tail[:240]}")
            else:
                diag.append(f"{url} ({'CPU' if use_cpu else 'GPU'}) HTTP {status}: {detail_raw[:400]}")

            if use_cpu:
                break
            if status < 400:
                break
            if _embedding_should_retry_cpu(http_status=status, detail_lower=detail_lower):
                continue
            break

        return None

    try:
        out = await embed_round(url_embed, modern=True)
        if out:
            return out
        out = await embed_round(url_legacy, modern=False)
        if out:
            return out

        merged = "; ".join(diag)
        merged_lc = merged.lower()
        if _looks_like_ollama_model_pull_missing(merged_lc):
            raise OllamaHttpError(
                f"Embedding model '{model}' not found in Ollama at {normalized}. "
                f"Run 'ollama pull {model}' to install it."
            )
        raise OllamaHttpError(
            "Could not obtain embeddings from Ollama (/api/embed and /api/embeddings failed): "
            f"{merged[:1600]}",
        )
    finally:
        if own_client:
            await client.aclose()


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
            except httpx.ReadTimeout as exc:
                log.warning(
                    f"{ctx}_read_timeout",
                    extra={
                        "attempt": attempt_label,
                        "timeout_s": timeout_s,
                        "elapsed_ms": round((time.monotonic() - t0) * 1000),
                    },
                )
                raise OllamaHttpError(
                    f"Ollama chat timed out after {timeout_s:.0f}s waiting for the full response. "
                    "Large prompts (e.g. AI macro brief over many comments) or slow/remote models may need "
                    "YOUTUBE_SCRAPE_ANALYTICS_MACRO_LLM_TIMEOUT_S (macro brief; default 420) or "
                    "YOUTUBE_SCRAPE_OLLAMA_TIMEOUT_S (chat and other calls)."
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

            # Provide helpful error messages for common Ollama failures
            error_msg = f"Ollama HTTP {resp.status_code}: {last_detail}"
            if resp.status_code == 500 and "unexpected EOF" in last_detail.lower():
                error_msg = (
                    f"Ollama model crashed (HTTP 500: unexpected EOF). "
                    f"This usually means the context exceeded the model's limit. "
                    f"Try: 1) Reduce RAG context in Settings, 2) Use a model with larger context window, "
                    f"3) Shorten your conversation history. Error: {last_detail}"
                )
            elif resp.status_code == 500:
                error_msg = (
                    f"Ollama model error (HTTP 500): {last_detail}. "
                    f"The model may have run out of memory or crashed. "
                    f"Try: 1) Restart Ollama, 2) Use a smaller model, 3) Check Ollama logs."
                )
            raise OllamaHttpError(error_msg)


async def ollama_chat_messages(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    json_format: bool,
    timeout_s: float,
    log_context: str | None = None,
) -> LlmChatResult:
    """POST ``/api/chat`` with a full message transcript (roles: system/user/assistant), non-streaming."""

    root = normalize_ollama_base_url(base_url)
    url = root.rstrip("/") + "/api/chat"
    base_payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": _think_request_field(model),
    }
    payloads: list[dict[str, Any]] = []
    if json_format:
        payloads.append({**base_payload, "format": "json"})
    payloads.append(base_payload)

    t = httpx.Timeout(timeout_s, connect=min(15.0, timeout_s))
    ctx = log_context or "ollama_chat_multi"
    async with httpx.AsyncClient(timeout=t) as client:
        last_detail = ""
        for i, payload in enumerate(payloads):
            attempt_label = f"{i + 1}/{len(payloads)}"
            uses_json_format = payload.get("format") == "json"
            t0 = time.monotonic()
            try:
                resp = await client.post(url, json=payload)
            except httpx.ConnectError as exc:
                raise OllamaHttpError(
                    f"Cannot connect to Ollama at {root.rstrip('/')}. "
                    "Start Ollama or set YOUTUBE_SCRAPE_OLLAMA_BASE_URL."
                ) from exc
            except httpx.ReadTimeout as exc:
                log.warning(
                    f"{ctx}_read_timeout",
                    extra={
                        "attempt": attempt_label,
                        "timeout_s": timeout_s,
                        "elapsed_ms": round((time.monotonic() - t0) * 1000),
                    },
                )
                raise OllamaHttpError(
                    f"Ollama chat timed out after {timeout_s:.0f}s waiting for the full response. "
                    "Large prompts (e.g. AI macro brief over many comments) or slow/remote models may need "
                    "YOUTUBE_SCRAPE_ANALYTICS_MACRO_LLM_TIMEOUT_S (macro brief; default 420) or "
                    "YOUTUBE_SCRAPE_OLLAMA_TIMEOUT_S (chat and other calls)."
                ) from exc
            except httpx.HTTPError as exc:
                raise OllamaHttpError(f"Ollama request failed: {exc}") from exc

            elapsed_ms = round((time.monotonic() - t0) * 1000)

            if resp.status_code < 400:
                try:
                    body = resp.json()
                except ValueError as exc:
                    raise OllamaHttpError("Ollama response was not JSON") from exc
                if not isinstance(body, dict):
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
                    pt, ct, tt = ollama_chat_usage_counts(body)
                    return LlmChatResult(
                        content=text.strip(),
                        prompt_tokens=pt,
                        completion_tokens=ct,
                        total_tokens=tt,
                    )

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
            if json_format and i == 0 and resp.status_code == 400 and len(payloads) > 1:
                log.info(
                    "ollama_retry_chat_multi_without_json_format",
                    extra={"detail": last_detail[:240]},
                )
                continue
            # Provide helpful error messages for common Ollama failures
            error_msg = f"Ollama HTTP {resp.status_code}: {last_detail}"
            if resp.status_code == 500 and "unexpected EOF" in last_detail.lower():
                error_msg = (
                    f"Ollama model crashed (HTTP 500: unexpected EOF). "
                    f"This usually means the context exceeded the model's limit. "
                    f"Try: 1) Reduce RAG context in Settings, 2) Use a model with larger context window, "
                    f"3) Shorten your conversation history. Error: {last_detail}"
                )
            elif resp.status_code == 500:
                error_msg = (
                    f"Ollama model error (HTTP 500): {last_detail}. "
                    f"The model may have run out of memory or crashed. "
                    f"Try: 1) Restart Ollama, 2) Use a smaller model, 3) Check Ollama logs."
                )
            raise OllamaHttpError(error_msg)
