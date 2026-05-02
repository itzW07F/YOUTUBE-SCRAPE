"""Concatenate scrape artifacts into a bounded text blob for Analytics LLM chat."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from youtube_scrape.adapters.analytics_artifacts import envelope_inner_data, read_json_file, read_metadata_history_jsonl
from youtube_scrape.domain.analytics_models import VideoMetricsSummary
from youtube_scrape.application.analytics_ollama_report import build_comment_digest_for_llm
from youtube_scrape.application.analytics_snapshot import video_metrics_from_metadata
from youtube_scrape.domain.analytics_aggregate import flatten_comment_nodes


@dataclass(frozen=True)
class ScrapeContextPack:
    """Result of assembling on-disk scrape text within a character budget."""

    text: str
    warnings: list[str]


_TRUNC_SUFFIX = "\n… [truncated by analytics context budget]"


def _read_text_bounded(path: Path, *, warn_key: str, warnings: list[str]) -> str | None:
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        warnings.append(f"Could not read {path.name} ({warn_key}); skipped.")
        return None
    return raw


def _append_section(
    parts: list[str],
    *,
    heading: str,
    body: str | None,
    remaining: list[int],
    warnings: list[str],
    truncation_note: str,
) -> None:
    """Append ``heading`` + ``body``; decrement ``remaining`` (single-element list hack for mutability)."""

    if body is None or not body.strip():
        return
    budget = remaining[0]
    header = f"\n\n## {heading}\n\n"
    need = len(header) + len(body)
    if need <= budget:
        parts.append(header + body)
        remaining[0] -= need
        return
    avail = budget - len(header) - len(_TRUNC_SUFFIX)
    if avail < 200:
        warnings.append(truncation_note)
        remaining[0] = 0
        return
    parts.append(header + body[:avail] + _TRUNC_SUFFIX)
    warnings.append(truncation_note)
    remaining[0] = 0


def _comments_block(
    output_dir: Path,
    *,
    metrics: VideoMetricsSummary | None,
    preferred_raw: str | None,
    remaining: list[int],
    warnings: list[str],
) -> str | None:
    """Prefer full JSON text; substitute digest when the raw corpus does not fit the remaining budget."""

    header = "\n\n## comments\n\n"
    budget = remaining[0]
    if preferred_raw is not None and preferred_raw.strip():
        need = len(header) + len(preferred_raw)
        if need <= budget:
            remaining[0] -= need
            return header + preferred_raw
        warnings.append(
            "comments.json is too large for the remaining context budget — using stratified digest instead "
            "(not full comment corpus)."
        )
    flat_any = None
    cenv = read_json_file(output_dir / "comments.json")
    if cenv is None:
        return None
    data = envelope_inner_data(cenv)
    raw_comments = data.get("comments")
    inner_flat: list[dict[str, Any]] = []
    if isinstance(raw_comments, list):
        inner_flat = flatten_comment_nodes(raw_comments)
    if not inner_flat:
        return None
    digest_budget = budget - len(header) - len(_TRUNC_SUFFIX)
    if digest_budget < 800:
        warnings.append("No room left for comments in context budget.")
        remaining[0] = 0
        return header + "(comments present but omitted — context budget exhausted)"
    digest, _meta = build_comment_digest_for_llm(inner_flat, metrics, max_chars=max(800, digest_budget))
    chunk = header + digest
    if len(chunk) > budget:
        avail = budget - len(header) - len(_TRUNC_SUFFIX)
        if avail < 200:
            remaining[0] = 0
            return header + "(comments digest omitted — budget exhausted)"
        chunk = header + digest[:avail] + _TRUNC_SUFFIX
        warnings.append("Comment digest truncated to fit context budget.")
    remaining[0] = max(0, budget - len(chunk))
    return chunk


def build_scrape_mini_header(output_dir: Path, warnings: list[str]) -> str:
    """Compact, human-readable metadata block for RAG header (no full JSON dump)."""

    env = read_json_file(output_dir / "video.json")
    if env is None:
        warnings.append("video.json missing — metadata header empty.")
        return "(No video.json — metadata unknown.)"
    inner = envelope_inner_data(env)
    meta = inner.get("metadata")
    if not isinstance(meta, dict):
        meta = inner if isinstance(inner, dict) else {}
    metrics = video_metrics_from_metadata(meta) if isinstance(meta, dict) else None
    lines: list[str] = []
    if metrics:
        if metrics.video_id:
            lines.append(f"video_id: {metrics.video_id}")
        if metrics.title:
            lines.append(f"title: {metrics.title}")
        if metrics.channel_title:
            lines.append(f"channel: {metrics.channel_title}")
        if metrics.published_at:
            lines.append(f"published_at: {metrics.published_at}")
        if metrics.view_count is not None:
            lines.append(f"views: {metrics.view_count}")
        if metrics.like_count is not None:
            lines.append(f"likes: {metrics.like_count}")
        if metrics.comment_count is not None:
            lines.append(f"comments (public total): {metrics.comment_count}")
        if metrics.duration_seconds is not None:
            lines.append(f"duration_s: {metrics.duration_seconds}")
    desc = meta.get("description") if isinstance(meta, dict) else None
    if isinstance(desc, str) and desc.strip():
        d = desc.strip()
        cap = 2000
        if len(d) > cap:
            d = d[:cap] + "…"
        lines.append(f"description_excerpt:\n{d}")
    if not lines:
        return "(video.json present but no usable metadata fields.)"
    return "\n".join(lines)


def build_scrape_context_pack(output_dir: Path, *, max_chars: int = 180_000) -> ScrapeContextPack:
    """Aggregate text artifacts from ``output_dir`` up to ``max_chars``."""

    warnings: list[str] = []
    remaining = [max(1, max_chars)]
    parts: list[str] = []
    opener = "# Scraped data bundle\n\nFolders on disk:\n"
    opener += (
        "This blob is assembled from scrape outputs (video metadata, transcript if present, history, comments, thumbnails "
        "manifest). Media files under ``download/`` and image binaries are not included.\n"
    )
    if remaining[0] < len(opener) + 32:
        return ScrapeContextPack(text=_TRUNC_SUFFIX.strip(), warnings=["Context budget extremely small — raise max_chars."])
    parts.append(opener)
    remaining[0] -= len(opener)

    video_path = output_dir / "video.json"
    env_for_metrics = read_json_file(video_path)
    video_raw = _read_text_bounded(video_path, warn_key="video", warnings=warnings)
    metrics_inner: VideoMetricsSummary | None = None
    if env_for_metrics is not None:
        inner = envelope_inner_data(env_for_metrics)
        meta = inner.get("metadata")
        if isinstance(meta, dict):
            metrics_inner = video_metrics_from_metadata(meta)
    if video_raw is None:
        warnings.append("video.json missing.")
    _append_section(
        parts,
        heading="video.json",
        body=video_raw,
        remaining=remaining,
        warnings=warnings,
        truncation_note="video.json truncated.",
    )

    transcript_body: str | None = None
    for suf in ("txt", "vtt", "json"):
        p = output_dir / f"transcript.{suf}"
        t = _read_text_bounded(p, warn_key=f"transcript.{suf}", warnings=warnings)
        if t is not None:
            transcript_body = t
            break
    _append_section(
        parts,
        heading="transcript",
        body=transcript_body,
        remaining=remaining,
        warnings=warnings,
        truncation_note="Transcript truncated (first match of transcript.txt / .vtt / .json).",
    )

    history_lines = read_metadata_history_jsonl(output_dir / "metadata_history.jsonl")
    mh_text: str | None = None
    if history_lines:
        mh_text = "\n".join(json.dumps(row, ensure_ascii=False) for row in history_lines)
    else:
        if (output_dir / "metadata_history.jsonl").exists():
            warnings.append("metadata_history.jsonl empty or unreadable.")
    _append_section(
        parts,
        heading="metadata_history.jsonl",
        body=mh_text,
        remaining=remaining,
        warnings=warnings,
        truncation_note="metadata_history.jsonl truncated.",
    )

    comments_raw = _read_text_bounded(output_dir / "comments.json", warn_key="comments", warnings=warnings)
    cb = _comments_block(output_dir, metrics=metrics_inner, preferred_raw=comments_raw, remaining=remaining, warnings=warnings)
    if cb:
        parts.append(cb)

    thumbs = read_json_file(output_dir / "thumbnails.json")
    thumbs_txt: str | None = None
    if thumbs is not None:
        try:
            thumbs_txt = json.dumps(thumbs, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            thumbs_txt = None
            warnings.append("thumbnails.json could not be serialized; skipped.")
    _append_section(
        parts,
        heading="thumbnails.json",
        body=thumbs_txt,
        remaining=remaining,
        warnings=warnings,
        truncation_note="thumbnails.json truncated.",
    )

    text = "".join(parts).strip()
    if not text:
        return ScrapeContextPack(
            text="(No readable scrape artifacts in this folder.)",
            warnings=warnings or ["Pack is empty."],
        )
    return ScrapeContextPack(text=text, warnings=warnings)
