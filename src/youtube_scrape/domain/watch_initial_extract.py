"""Supplement player-derived metadata from ``ytInitialData`` (watch layout)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from youtube_scrape.domain.engagement_count_parse import parse_engagement_count_text
from youtube_scrape.domain.models import VideoMetadata
from youtube_scrape.domain.time_normalize import parse_published_text_to_utc


def _iter_primary_column_cells(initial: dict[str, Any]) -> list[dict[str, Any]]:
    tc = (initial.get("contents") or {}).get("twoColumnWatchNextResults")
    if not isinstance(tc, dict):
        return []
    results_block = (tc.get("results") or {}).get("results")
    if not isinstance(results_block, dict):
        return []
    contents = results_block.get("contents")
    if not isinstance(contents, list):
        return []
    return [c for c in contents if isinstance(c, dict)]


def find_video_primary_info_renderer(initial: dict[str, Any]) -> dict[str, Any] | None:
    for cell in _iter_primary_column_cells(initial):
        vpir = cell.get("videoPrimaryInfoRenderer")
        if isinstance(vpir, dict):
            return vpir
    return None


def _button_view_count(button_view: dict[str, Any]) -> int | None:
    acc = button_view.get("accessibilityText")
    if isinstance(acc, str):
        n = parse_engagement_count_text(acc)
        if n is not None:
            return n
    title = button_view.get("title")
    if title is not None and not isinstance(title, dict):
        return parse_engagement_count_text(str(title))
    return None


def _count_from_toggle_outer(toggle_outer: dict[str, Any]) -> int | None:
    inner = toggle_outer.get("toggleButtonViewModel")
    if not isinstance(inner, dict):
        return None
    inner2 = inner.get("toggleButtonViewModel")
    if not isinstance(inner2, dict):
        inner2 = inner
    for key in ("defaultButtonViewModel", "toggledButtonViewModel"):
        wrap = inner2.get(key)
        if not isinstance(wrap, dict):
            continue
        btn_vm = wrap.get("buttonViewModel")
        if isinstance(btn_vm, dict):
            n = _button_view_count(btn_vm)
            if n is not None:
                return n
    return None


def extract_like_dislike_from_vpir(vpir: dict[str, Any]) -> tuple[int | None, int | None]:
    menu = (vpir.get("videoActions") or {}).get("menuRenderer")
    if not isinstance(menu, dict):
        return None, None
    buttons = menu.get("topLevelButtons")
    if not isinstance(buttons, list):
        return None, None
    like_n: int | None = None
    dislike_n: int | None = None
    for btn in buttons:
        if not isinstance(btn, dict):
            continue
        seg = btn.get("segmentedLikeDislikeButtonViewModel")
        if not isinstance(seg, dict):
            continue
        like_branch = seg.get("likeButtonViewModel") or {}
        like_inner = like_branch.get("likeButtonViewModel") if isinstance(like_branch, dict) else {}
        if isinstance(like_inner, dict):
            toggle = like_inner.get("toggleButtonViewModel")
            if isinstance(toggle, dict):
                like_n = _count_from_toggle_outer(toggle)
        d_branch = seg.get("dislikeButtonViewModel") or {}
        d_inner = d_branch.get("dislikeButtonViewModel") if isinstance(d_branch, dict) else {}
        if isinstance(d_inner, dict):
            dtoggle = d_inner.get("toggleButtonViewModel")
            if isinstance(dtoggle, dict):
                dislike_n = _count_from_toggle_outer(dtoggle)
        break
    return like_n, dislike_n


def enrich_video_metadata_from_initial(
    meta: VideoMetadata,
    initial: dict[str, Any],
    *,
    now_utc: datetime | None = None,
) -> VideoMetadata:
    """Fill gaps using ``videoPrimaryInfoRenderer`` (likes and human-readable publish date)."""
    if not initial:
        return meta
    vpir = find_video_primary_info_renderer(initial)
    if vpir is None:
        return meta
    updates: dict[str, Any] = {}
    clock = _to_utc_naive(now_utc)
    date_text_raw = (vpir.get("dateText") or {}).get("simpleText")
    if isinstance(date_text_raw, str):
        date_text = date_text_raw.strip()
        if date_text:
            if meta.published_text is None:
                updates["published_text"] = date_text
            if meta.published_at is None:
                parsed = parse_published_text_to_utc(date_text, now_utc=clock)
                if parsed is not None:
                    updates["published_at"] = parsed
    like_n, dislike_n = extract_like_dislike_from_vpir(vpir)
    if meta.like_count is None and like_n is not None:
        updates["like_count"] = like_n
    if meta.dislike_count is None and dislike_n is not None:
        updates["dislike_count"] = dislike_n
    if not updates:
        return meta
    return meta.model_copy(update=updates)


def _to_utc_naive(now_utc: datetime | None) -> datetime:
    if now_utc is None:
        return datetime.now(UTC)
    if now_utc.tzinfo is None:
        return now_utc.replace(tzinfo=UTC)
    return now_utc.astimezone(UTC)
