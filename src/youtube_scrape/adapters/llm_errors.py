"""Shared exceptions for LLM HTTP clients."""


class LlmTransportError(RuntimeError):
    """Non-success transport, auth, or vendor response for any analytics LLM backend."""
