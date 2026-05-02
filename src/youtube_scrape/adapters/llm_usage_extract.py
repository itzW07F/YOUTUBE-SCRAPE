"""Parse token usage blobs from heterogeneous LLM JSON responses."""

from __future__ import annotations

from typing import Any


def _nonneg_int(raw: Any) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int) and raw >= 0:
        return raw
    if isinstance(raw, float) and raw.is_integer() and raw >= 0:
        return int(raw)
    return None


def ollama_chat_usage_counts(body: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    """Map Ollama /api/chat counters to (prompt-ish, completion, total)."""

    pt = (
        _nonneg_int(body.get("prompt_eval_count"))
        if "prompt_eval_count" in body
        else _nonneg_int(body.get("prompt_tokens"))
    )
    ct = _nonneg_int(body.get("eval_count")) if "eval_count" in body else _nonneg_int(body.get("completion_tokens"))
    tot_raw = _nonneg_int(body.get("total_tokens"))
    if tot_raw is not None:
        return pt, ct, tot_raw
    if pt is not None and ct is not None:
        return pt, ct, pt + ct
    return pt, ct, None


def openai_compat_usage_counts(body: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return None, None, None
    pt = _nonneg_int(usage.get("prompt_tokens"))
    ct = _nonneg_int(usage.get("completion_tokens"))
    tt = _nonneg_int(usage.get("total_tokens"))
    if tt is None and pt is not None and ct is not None:
        tt = pt + ct
    return pt, ct, tt


def anthropic_usage_counts(body: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return None, None, None
    ipt = usage.get("input_tokens")
    opt = usage.get("output_tokens")
    pt = _nonneg_int(ipt)
    ct = _nonneg_int(opt)
    tt = _nonneg_int(usage.get("total_tokens"))
    if tt is None and pt is not None and ct is not None:
        tt = pt + ct
    return pt, ct, tt


def gemini_usage_counts(body: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    um = body.get("usageMetadata")
    if not isinstance(um, dict):
        return None, None, None
    pt = _nonneg_int(um.get("promptTokenCount"))
    ct = _nonneg_int(um.get("candidatesTokenCount"))
    tt = _nonneg_int(um.get("totalTokenCount"))
    if tt is None and pt is not None and ct is not None:
        tt = pt + ct
    return pt, ct, tt
