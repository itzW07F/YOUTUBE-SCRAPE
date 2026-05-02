"""Typed multi-turn chat completion payloads for analytics LLM adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LlmChatResult:
    """Assistant text plus optional provider usage metadata."""

    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
