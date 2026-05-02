"""Multi-turn analytics chat over scraped folder context (configured LLM provider)."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

from youtube_scrape.adapters.llm_errors import LlmTransportError
from youtube_scrape.adapters.llm_providers import build_analytics_llm
from youtube_scrape.application.analytics_gui_llm_resolve import effective_analytics_llm_settings
from youtube_scrape.application.analytics_scrape_context_pack import build_scrape_context_pack
from youtube_scrape.application.analytics_scrape_rag import analytics_rag_eligible, try_resolve_hybrid_context_pack
from youtube_scrape.domain.analytics_models import AnalyticsChatMessage, AnalyticsChatResponse, GuiAnalyticsLlmOverlay

_DEFAULT_CHAT_CONTEXT_CHARS = 180_000
_MAX_CHAT_TURNS = 40

_CHAT_SYSTEM_PROMPT = (
    "You are an assistant helping someone interpret ONE YouTube video scrape bundled as raw text excerpts "
    "(metadata, optional transcript lines, periodic metadata snapshots, comments, thumbnails manifest).\n"
    "Stay grounded in those excerpts — do not invent video content, unseen comments, or off-site facts.\n"
    "If information is missing, say so succinctly.\n"
    "Reply in plain language (not JSON)."
)

_CHAT_SYSTEM_PROMPT_RAG = (
    "You are an assistant for ONE YouTube video scrape. The application built your context using "
    "**embedding-based retrieval (RAG)** over a **local vector index** of this folder's scraped files "
    "(comments, transcript slices, metadata, etc.). You see a header plus **retrieved_excerpts** chosen by "
    "similarity to the user's latest question — that is the RAG / Vector DB pipeline (not live web browsing).\n"
    "If the user asks whether you use RAG or a vector database, answer **yes**: your material is from that "
    "local retrieval step, grounded only in those excerpts.\n"
    "Stay grounded only in that material — do not invent video content, unseen comments, or off-site facts.\n"
    "If information is missing, say so succinctly.\n"
    "Reply in plain language (not JSON)."
)

_PRIMING_REPLY = (
    "Understood. I will rely only on the scraped bundle provided for this conversation and will flag "
    "uncertainty where the excerpts are silent."
)

_PRIMING_REPLY_RAG = (
    "Understood. I will answer using only the metadata header and retrieved_excerpts from this folder's "
    "local vector RAG index, and I will flag uncertainty where those excerpts are silent."
)


def _estimate_tokens(chars: int) -> int:
    return max(0, chars // 4)


def _payload_char_estimate(system: str | None, transcript: list[dict[str, str]]) -> int:
    parts: list[str] = []
    if system and system.strip():
        parts.append(system.strip())
    for msg in transcript:
        parts.append(f"{msg['role']}:{msg['content']}")
    return len("\n".join(parts))


def _validate_visible_messages(messages: list[AnalyticsChatMessage]) -> list[dict[str, str]]:
    if len(messages) > _MAX_CHAT_TURNS:
        raise ValueError(f"Too many conversational turns ({len(messages)}); max is {_MAX_CHAT_TURNS}.")
    out: list[dict[str, str]] = []
    for idx, msg in enumerate(messages):
        stripped = msg.content.strip()
        if not stripped:
            raise ValueError(f"Empty message content at position {idx}.")
        expect = "user" if idx % 2 == 0 else "assistant"
        if msg.role != expect:
            raise ValueError(
                f'Message {idx + 1} must be role "{expect}" for alternating transcript (starts with user).'
            )
        out.append({"role": msg.role, "content": stripped})
    if not out:
        raise ValueError("Conversation is empty.")
    if out[-1]["role"] != "user":
        raise ValueError("Last message must be from the user so the assistant can reply.")
    return out


async def run_analytics_llm_chat(
    output_dir: Path,
    *,
    messages: list[AnalyticsChatMessage],
    gui_overlay: GuiAnalyticsLlmOverlay | None = None,
    max_context_chars: int = _DEFAULT_CHAT_CONTEXT_CHARS,
) -> AnalyticsChatResponse:
    """Build scrape context priming pairs, prepend to visible ``messages``, and return assistant text."""

    settings = effective_analytics_llm_settings(gui=gui_overlay)
    if not settings.analytics_ollama_enabled:
        raise LlmTransportError("LLM analytics disabled via settings (analytics_ollama_enabled=false).")

    visible = _validate_visible_messages(messages)
    last_user_q = visible[-1]["content"]
    hybrid_pack, rag_diag = await try_resolve_hybrid_context_pack(
        output_dir, user_query=last_user_q, settings=settings
    )
    if hybrid_pack is not None:
        pack = hybrid_pack
        sys_prompt = _CHAT_SYSTEM_PROMPT_RAG
        priming_ack = _PRIMING_REPLY_RAG
    else:
        # RAG not eligible - explain why
        pack = build_scrape_context_pack(output_dir, max_chars=max_context_chars)
        sys_prompt = _CHAT_SYSTEM_PROMPT
        priming_ack = _PRIMING_REPLY
        
        # Add diagnostic warning about why RAG wasn't used
        if not settings.analytics_rag_enabled:
            pack.warnings.append("RAG disabled in settings (analytics_rag_enabled=false). Using full context.")
        elif settings.analytics_llm_provider != "ollama":
            pack.warnings.append(f"RAG requires Ollama provider (current: {settings.analytics_llm_provider}). Using full context.")
        elif not settings.analytics_ollama_enabled:
            pack.warnings.append("RAG requires analytics to be enabled (analytics_ollama_enabled=false). Using full context.")
        else:
            pack.warnings.append("RAG eligibility check failed. Using full context (may cause truncation).")
        
        fb = rag_diag.get("_fallback_warnings")
        if isinstance(fb, list):
            pack.warnings.extend([str(x) for x in fb if x])

    backend = build_analytics_llm(settings)
    await backend.ensure_ready(timeout_s=min(settings.ollama_timeout_s, 60.0))

    primed: list[dict[str, str]] = [
        {"role": "user", "content": pack.text},
        {"role": "assistant", "content": priming_ack},
    ]
    transcript = primed + visible
    scrape_chars = len(pack.text)
    req_prompt_chars = _payload_char_estimate(sys_prompt, transcript)

    t0 = time.perf_counter()
    lm_out = await backend.chat_messages(
        system=sys_prompt,
        messages=transcript,
        json_format=False,
        timeout_s=settings.ollama_timeout_s,
        log_context="analytics_chat",
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    provider = settings.analytics_llm_provider
    tot_llm = lm_out.total_tokens
    if tot_llm is None and lm_out.prompt_tokens is not None and lm_out.completion_tokens is not None:
        tot_llm = lm_out.prompt_tokens + lm_out.completion_tokens

    # Get mode from RAG result
    rag_mode: Literal["legacy", "hybrid", "fallback_meta"] | None = rag_diag.get("analytics_rag_mode")
    log.info(
        "analytics_chat_rag_result",
        extra={
            "rag_mode": rag_mode,
            "hybrid_pack_was_none": hybrid_pack is None,
            "rag_diag": rag_diag,
        },
    )
    if rag_mode is None and analytics_rag_eligible(settings):
        rag_mode = "legacy"

    def _rag_int(key: str) -> int | None:
        v = rag_diag.get(key)
        return int(v) if isinstance(v, int) else None

    return AnalyticsChatResponse(
        assistant=lm_out.content.strip(),
        warnings=pack.warnings,
        provider=provider,
        model=settings.analytics_llm_model_label(),
        llm_latency_ms=latency_ms,
        scrape_bundle_chars=scrape_chars,
        estimated_scrape_bundle_tokens=_estimate_tokens(scrape_chars),
        estimated_request_prompt_tokens=_estimate_tokens(req_prompt_chars),
        prompt_tokens=lm_out.prompt_tokens,
        completion_tokens=lm_out.completion_tokens,
        total_tokens=tot_llm,
        analytics_rag_mode=rag_mode,
        analytics_rag_chunks_used=_rag_int("analytics_rag_chunks_used"),
        analytics_rag_index_build_ms=_rag_int("analytics_rag_index_build_ms"),
        analytics_rag_embed_ms=_rag_int("analytics_rag_embed_ms"),
    )
