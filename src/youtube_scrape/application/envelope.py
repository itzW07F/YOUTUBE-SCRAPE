"""Wrap CLI outputs in a versioned envelope."""

from __future__ import annotations

from typing import Any, Literal

from youtube_scrape.domain.models import ResultEnvelope
from youtube_scrape.settings import Settings


def make_envelope(
    *,
    settings: Settings,
    kind: Literal["video", "comments", "transcript", "download", "thumbnails"],
    data: dict[str, Any],
) -> ResultEnvelope:
    """Build a :class:`ResultEnvelope` using ``settings.output_schema_version``."""
    return ResultEnvelope(schema_version=settings.output_schema_version, kind=kind, data=data)
