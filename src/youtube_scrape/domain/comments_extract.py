"""Walk ``ytInitialData`` / continuation payloads for comment threads."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from youtube_scrape.domain.constants import (
    COMMENT_KEY,
    COMMENT_REPLIES_KEY,
    COMMENT_THREAD_KEY,
    CONTINUATION_ITEM_KEY,
)
from youtube_scrape.domain.models import CommentRecord
from youtube_scrape.domain.time_normalize import parse_published_text_to_utc

_COMMENT_ENTITY_MARKER = "commentEntityPayload"
_COMMENT_REPLY_RENDERER = "commentReplyRenderer"


def _iter_nested_dicts(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_nested_dicts(v)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_nested_dicts(item)


def _parse_comment_renderer(
    renderer: dict[str, Any],
    *,
    is_reply: bool,
    parent_comment_id: str | None,
    now_utc: datetime,
) -> CommentRecord:
    cid = str(renderer.get("commentId") or "")
    text_runs = renderer.get("contentText", {}).get("runs") or []
    text = "".join(str(part.get("text", "")) for part in text_runs if isinstance(part, dict))
    author = (renderer.get("authorText") or {}).get("simpleText")
    author_endpoint = ((renderer.get("authorEndpoint") or {}).get("browseEndpoint") or {}).get("browseId")
    published = (renderer.get("publishedTimeText") or {}).get("simpleText")
    likes = renderer.get("likeCount")
    try:
        like_count = int(likes) if likes is not None else None
    except (TypeError, ValueError):
        like_count = None
    return CommentRecord(
        comment_id=cid,
        text=text,
        author=author,
        author_channel_id=str(author_endpoint) if author_endpoint else None,
        published_text=published,
        published_at=parse_published_text_to_utc(published, now_utc=now_utc),
        like_count=like_count,
        is_reply=is_reply,
        parent_comment_id=parent_comment_id,
    )


def extract_threads_from_renderer(
    thread: dict[str, Any],
    *,
    max_replies_per_thread: int | None = None,
    now_utc: datetime | None = None,
) -> list[CommentRecord]:
    """Expand a ``commentThreadRenderer`` into top-level + reply records."""
    out: list[CommentRecord] = []
    reference_now = now_utc or datetime.now(UTC)
    comment = (thread.get("comment") or {}).get(COMMENT_KEY)
    if not isinstance(comment, dict):
        return out
    top = _parse_comment_renderer(comment, is_reply=False, parent_comment_id=None, now_utc=reference_now)
    out.append(top)
    replies_obj = thread.get("replies", {}).get(COMMENT_REPLIES_KEY)
    if isinstance(replies_obj, dict):
        for idx, item in enumerate(replies_obj.get("contents") or []):
            if max_replies_per_thread is not None and idx >= max_replies_per_thread:
                break
            rep = item.get(COMMENT_KEY)
            if isinstance(rep, dict):
                out.append(
                    _parse_comment_renderer(
                        rep,
                        is_reply=True,
                        parent_comment_id=top.comment_id,
                        now_utc=reference_now,
                    )
                )
    return out


def response_has_comment_entities(resp: dict[str, Any]) -> bool:
    """Return True if ``resp`` looks like a comment Innertube surface (not e.g. watch-next feed)."""
    for node in _iter_nested_dicts(resp):
        if not isinstance(node, dict):
            continue
        if _COMMENT_ENTITY_MARKER in node or _COMMENT_REPLY_RENDERER in node:
            return True
        if COMMENT_THREAD_KEY in node:
            return True
    return False


def _compact_int_from_display(s: str) -> int | None:
    """Parse counts like ``183``, ``1.2K``, ``2M`` from toolbar strings."""
    raw = str(s).strip().replace(",", "")
    if not raw:
        return None
    mult = 1
    upper = raw[-1].upper()
    if upper == "K":
        mult = 1000
        raw = raw[:-1]
    elif upper == "M":
        mult = 1_000_000
        raw = raw[:-1]
    elif upper == "B":
        mult = 1_000_000_000
        raw = raw[:-1]
    try:
        return int(float(raw) * mult)
    except (TypeError, ValueError):
        return None


def _like_count_from_toolbar(toolbar: Any) -> int | None:
    if not isinstance(toolbar, dict):
        return None
    raw = toolbar.get("likeCountNotliked") or toolbar.get("likeCountLiked")
    if raw is None:
        a11y = toolbar.get("likeCountA11y")
        if isinstance(a11y, str):
            m = re.search(r"([\d,.]+[KMBk]?)", a11y)
            if m:
                return _compact_int_from_display(m.group(1))
        return None
    if isinstance(raw, int):
        return raw
    return _compact_int_from_display(str(raw))


def _parent_id_from_entity_comment_id(comment_id: str, reply_level: int) -> str | None:
    """YouTube reply ids are ``<topId>.<suffix>``."""
    if reply_level <= 0:
        return None
    if "." not in comment_id:
        return None
    return comment_id.split(".", 1)[0]


def extract_comments_from_initial_data(
    data: dict[str, Any],
    *,
    max_replies_per_thread: int | None = None,
    now_utc: datetime | None = None,
) -> list[CommentRecord]:
    """Collect all comments reachable without continuations."""
    records: list[CommentRecord] = []
    reference_now = now_utc or datetime.now(UTC)
    for node in _iter_nested_dicts(data):
        thread = node.get(COMMENT_THREAD_KEY)
        if isinstance(thread, dict):
            records.extend(
                extract_threads_from_renderer(
                    thread,
                    max_replies_per_thread=max_replies_per_thread,
                    now_utc=reference_now,
                )
            )
    return records


def extract_comments_from_entity_mutations(
    data: dict[str, Any],
    *,
    include_replies: bool = True,
    now_utc: datetime | None = None,
) -> list[CommentRecord]:
    """Collect comments from ``frameworkUpdates.entityBatchUpdate.mutations`` (web client).

    YouTube increasingly returns top-level comments only in entity mutations on ``youtubei/v1/next``
    instead of embedding ``commentThreadRenderer`` trees in the JSON response.
    """
    fu = data.get("frameworkUpdates")
    if not isinstance(fu, dict):
        return []
    eb = fu.get("entityBatchUpdate")
    if not isinstance(eb, dict):
        return []
    muts = eb.get("mutations")
    if not isinstance(muts, list):
        return []
    out: list[CommentRecord] = []
    reference_now = now_utc or datetime.now(UTC)
    for mut in muts:
        if not isinstance(mut, dict):
            continue
        pay = mut.get("payload")
        if not isinstance(pay, dict):
            continue
        cep = pay.get("commentEntityPayload")
        if not isinstance(cep, dict):
            continue
        props = cep.get("properties")
        if not isinstance(props, dict):
            continue
        cid = str(props.get("commentId") or "")
        if not cid:
            continue
        reply_level_raw = props.get("replyLevel", 0)
        try:
            reply_level = int(reply_level_raw) if reply_level_raw is not None else 0
        except (TypeError, ValueError):
            reply_level = 0
        is_reply = reply_level > 0
        if is_reply and not include_replies:
            continue
        content_obj = props.get("content")
        if isinstance(content_obj, dict):
            text = str(content_obj.get("content") or "")
        else:
            text = str(content_obj or "")
        published = props.get("publishedTime")
        author_obj = cep.get("author")
        author: str | None = None
        ach: str | None = None
        if isinstance(author_obj, dict):
            author = author_obj.get("displayName") if isinstance(author_obj.get("displayName"), str) else None
            ach_raw = author_obj.get("channelId")
            ach = str(ach_raw) if ach_raw else None
        toolbar = cep.get("toolbar")
        like_count = _like_count_from_toolbar(toolbar)
        parent_id = _parent_id_from_entity_comment_id(cid, reply_level)
        out.append(
            CommentRecord(
                comment_id=cid,
                text=text,
                author=author,
                author_channel_id=ach,
                published_text=str(published) if published is not None else None,
                published_at=parse_published_text_to_utc(
                    str(published) if published is not None else None,
                    now_utc=reference_now,
                ),
                like_count=like_count,
                is_reply=is_reply,
                parent_comment_id=parent_id,
            )
        )
    return out


def extract_comment_records_from_response(
    data: dict[str, Any],
    *,
    max_replies_per_thread: int | None,
    include_replies: bool,
    now_utc: datetime | None = None,
) -> list[CommentRecord]:
    """Merge classic renderer comments and entity-mutation comments; dedupe by ``comment_id``."""
    seen: set[str] = set()
    merged: list[CommentRecord] = []
    for group in (
        extract_comments_from_initial_data(
            data,
            max_replies_per_thread=max_replies_per_thread,
            now_utc=now_utc,
        ),
        extract_comments_from_entity_mutations(
            data,
            include_replies=include_replies,
            now_utc=now_utc,
        ),
    ):
        for c in group:
            if not c.comment_id or c.comment_id in seen:
                continue
            seen.add(c.comment_id)
            merged.append(c)
    return merged


def extract_continuation_tokens(data: dict[str, Any]) -> list[str]:
    """Collect youtubei continuation tokens from a response tree."""
    tokens: list[str] = []
    for node in _iter_nested_dicts(data):
        cont_item = node.get(CONTINUATION_ITEM_KEY)
        if isinstance(cont_item, dict):
            ep = cont_item.get("continuationEndpoint") or {}
            next_data = ep.get("continuationCommand") or {}
            token = next_data.get("token")
            if isinstance(token, str) and token:
                tokens.append(token)
        next_data = node.get("nextContinuationData")
        if isinstance(next_data, dict):
            token = next_data.get("continuation")
            if isinstance(token, str) and token:
                tokens.append(token)
    # de-dupe preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique
