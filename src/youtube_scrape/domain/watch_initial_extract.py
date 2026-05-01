"""Supplement player-derived metadata from ``ytInitialData`` (watch layout)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from youtube_scrape.domain.engagement_count_parse import parse_engagement_count_text
from youtube_scrape.domain.models import VideoMetadata
from youtube_scrape.domain.time_normalize import parse_published_text_to_utc

# Set on ``initial`` by the browser adapter after the comments panel hydrates in the DOM.
DOM_COMMENT_COUNT_SCRATCH_KEY: str = "_youtube_scrape_dom_comment_total"


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


def _iter_all_dicts(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_all_dicts(v)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_all_dicts(item)


def _text_from_runs(runs: Any) -> str | None:
    if not isinstance(runs, list):
        return None
    parts: list[str] = []
    for run in runs:
        if isinstance(run, dict) and run.get("text") is not None:
            parts.append(str(run.get("text", "")))
    out = "".join(parts).strip()
    return out or None


def _parse_comment_countish_dict(d: dict[str, Any]) -> int | None:
    """Parse a public comment total from renderer-shaped dicts (header / entry point)."""
    cc = d.get("commentCount")
    if isinstance(cc, dict):
        st = cc.get("simpleText")
        if isinstance(st, str):
            n = parse_engagement_count_text(st)
            if n is not None:
                return n
        runs_txt = _text_from_runs(cc.get("runs"))
        if runs_txt is not None:
            n = parse_engagement_count_text(runs_txt)
            if n is not None:
                return n
    ct = d.get("countText")
    if isinstance(ct, dict):
        runs_txt = _text_from_runs(ct.get("runs"))
        if runs_txt is not None:
            n = parse_engagement_count_text(runs_txt)
            if n is not None:
                return n
        st = ct.get("simpleText")
        if isinstance(st, str):
            n = parse_engagement_count_text(st)
            if n is not None:
                return n
    cnt = d.get("count")
    if isinstance(cnt, dict):
        st2 = cnt.get("simpleText")
        if isinstance(st2, str):
            n = parse_engagement_count_text(st2)
            if n is not None:
                return n
    ci = d.get("contextualInfo")
    if isinstance(ci, dict):
        runs_txt = _text_from_runs(ci.get("runs"))
        if runs_txt is not None:
            n = parse_engagement_count_text(runs_txt)
            if n is not None:
                return n
        st = ci.get("simpleText")
        if isinstance(st, str):
            n = parse_engagement_count_text(st)
            if n is not None:
                return n
    return None


# Match "9,999 Comments" / "2.5K Comments" in engagement / accessibility labels (primary column).
_COMMENT_TOTAL_LABEL_RE = re.compile(
    r"([\d,.]+(?:[KkMmBb])?)\s*Comments?\b",
    re.IGNORECASE,
)
# "Comments • 12,345" / "Comments · 2.6K" (section title variants under the player).
_COMMENT_LEADING_BEFORE_NUMBER_RE = re.compile(
    r"Comments?\s*[:\u2022·•]+\s*([\d,.]+(?:[KkMmBb])?\b)",
    re.IGNORECASE,
)


def _comment_total_from_visible_label_text(s: str | None) -> int | None:
    if not s or "comment" not in s.lower():
        return None
    norm = s.replace("\xa0", " ").strip()
    m = _COMMENT_TOTAL_LABEL_RE.search(norm)
    if m:
        return parse_engagement_count_text(m.group(1))
    m2 = _COMMENT_LEADING_BEFORE_NUMBER_RE.search(norm)
    if m2:
        return parse_engagement_count_text(m2.group(1))
    return None


def parse_public_comment_total_from_heading_text(text: str | None) -> int | None:
    """Parse counts like ``2,434,618 Comments`` from ``ytd-comments-header-renderer`` heading text."""
    if not text:
        return None
    return _comment_total_from_visible_label_text(text.replace("\xa0", " ").strip())


def _fallback_comment_totals_from_primary_column_text(initial: dict[str, Any]) -> list[int]:
    """Engagement row / accessibility labels under the video (avoids sidebar / related video ``commentCount``)."""
    out: list[int] = []
    for cell in _iter_primary_column_cells(initial):
        for node in _iter_all_dicts(cell):
            if not isinstance(node, dict):
                continue
            st = node.get("simpleText")
            if isinstance(st, str):
                n = _comment_total_from_visible_label_text(st)
                if n is not None:
                    out.append(n)
            runs = node.get("runs")
            if isinstance(runs, list):
                joined = _text_from_runs(runs)
                n = _comment_total_from_visible_label_text(joined)
                if n is not None:
                    out.append(n)
            acc = node.get("accessibility")
            if isinstance(acc, dict):
                ad = acc.get("accessibilityData")
                if isinstance(ad, dict) and isinstance(ad.get("label"), str):
                    n = _comment_total_from_visible_label_text(ad["label"])
                    if n is not None:
                        out.append(n)
    return out


def extract_public_comment_count_from_initial(initial: dict[str, Any]) -> int | None:
    """Parse total public comment count from watch ``ytInitialData``.

    Order matters: related / recommended surfaces can embed early ``commentCount`` nodes with
    wrong/stale values. Prefer comment header renderers, then primary-column labels, then the
    max of any remaining ``commentCount`` blobs (legacy / edge cases).
    """
    header_hits: list[int] = []
    for node in _iter_all_dicts(initial):
        if not isinstance(node, dict):
            continue
        for key in ("commentsHeaderRenderer", "commentsEntryPointHeaderRenderer"):
            sub = node.get(key)
            if isinstance(sub, dict):
                n = _parse_comment_countish_dict(sub)
                if n is not None:
                    header_hits.append(n)
    if header_hits:
        return max(header_hits)

    primary_hits = _fallback_comment_totals_from_primary_column_text(initial)
    if primary_hits:
        return max(primary_hits)

    generic: list[int] = []
    for node in _iter_all_dicts(initial):
        if not isinstance(node, dict) or "commentCount" not in node:
            continue
        n = _parse_comment_countish_dict(node)
        if n is not None:
            generic.append(n)
    return max(generic) if generic else None


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
    """Fill gaps from watch ``ytInitialData`` (primary info, comments header, etc.)."""
    if not initial:
        return meta
    updates: dict[str, Any] = {}

    dom_cc: int | None = None
    initial_for_json = initial
    raw_dom = initial.get(DOM_COMMENT_COUNT_SCRATCH_KEY)
    if isinstance(raw_dom, int) and raw_dom >= 0:
        dom_cc = raw_dom
    if dom_cc is not None or DOM_COMMENT_COUNT_SCRATCH_KEY in initial:
        initial_for_json = {k: v for k, v in initial.items() if k != DOM_COMMENT_COUNT_SCRATCH_KEY}

    # ytInitial comment header often lacks the numeric total; DOM hydration is authoritative then.
    public_cc = extract_public_comment_count_from_initial(initial_for_json)
    if dom_cc is not None:
        updates["comment_count"] = dom_cc
    elif public_cc is not None:
        updates["comment_count"] = public_cc

    vpir = find_video_primary_info_renderer(initial)
    if vpir is not None:
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
