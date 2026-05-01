"""Pure aggregation helpers for comment analytics."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from youtube_scrape.domain.analytics_models import (
    AuthorAggregate,
    CommentStats,
    CommentVolumeBucket,
    KeywordTerm,
    LikeCountBucket,
)

_WORD_RE = re.compile(r"[a-z][a-z0-9']+", re.IGNORECASE)

# Minimal English stopwords — analytics_keywords English-focused MVP.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "you",
        "your",
        "from",
        "have",
        "has",
        "had",
        "was",
        "were",
        "are",
        "but",
        "not",
        "what",
        "when",
        "where",
        "who",
        "why",
        "how",
        "all",
        "any",
        "can",
        "did",
        "its",
        "just",
        "like",
        "out",
        "our",
        "one",
        "get",
        "got",
        "too",
        "very",
        "will",
        "would",
        "could",
        "should",
        "about",
        "into",
        "than",
        "then",
        "them",
        "they",
        "their",
        "there",
        "here",
        "some",
        "more",
        "most",
        "also",
        "only",
        "even",
        "because",
        "video",
        "comment",
        "comments",
    }
)


def flatten_comment_nodes(nodes: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Expand hierarchical ``comments`` list (parents with ``replies``) into flat dict rows."""

    rows: list[dict[str, Any]] = []

    def walk(ns: Iterable[Mapping[str, Any]]) -> None:
        for raw in ns:
            replies = raw.get("replies")
            row = {k: v for k, v in raw.items() if k != "replies"}
            rows.append(row)
            if isinstance(replies, list) and replies:
                walk(replies)

    walk(nodes)
    return rows


def _parse_iso_day(published_at: str | None) -> str | None:
    if not published_at or not isinstance(published_at, str):
        return None
    s = published_at.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).date().isoformat()
    except ValueError:
        return None


def _like_bucket(n: int | None) -> str:
    if n is None or n <= 0:
        return "0"
    if n <= 5:
        return "1–5"
    if n <= 20:
        return "6–20"
    return "21+"


def build_comment_stats(
    flat: list[dict[str, Any]],
    *,
    top_level_count: int | None,
) -> CommentStats:
    day_counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    author_counts: Counter[str] = Counter()
    author_likes: Counter[str] = Counter()
    with_ts = 0
    reply_count = sum(1 for r in flat if r.get("is_reply"))

    for r in flat:
        day = _parse_iso_day(r.get("published_at")) if r.get("published_at") else None
        if day:
            with_ts += 1
            day_counts[day] += 1

        likes = r.get("like_count")
        li = int(likes) if isinstance(likes, int | float) and likes >= 0 else None
        bucket_counts[_like_bucket(li)] += 1

        auth = r.get("author")
        label = auth.strip() if isinstance(auth, str) and auth.strip() else "(unknown)"
        author_counts[label] += 1
        if li is not None:
            author_likes[label] += li

    volume = [CommentVolumeBucket(bucket_start=d, count=c) for d, c in sorted(day_counts.items())]
    likes_order = ["0", "1–5", "6–20", "21+"]
    like_buckets = [LikeCountBucket(label=lab, count=bucket_counts.get(lab, 0)) for lab in likes_order]

    top_authors = author_counts.most_common(15)
    aggregates: list[AuthorAggregate] = []
    for name, cnt in top_authors:
        agg_likes = author_likes[name]
        aggregates.append(
            AuthorAggregate(
                author=name,
                comment_count=cnt,
                total_likes=int(agg_likes) if agg_likes else None,
            )
        )

    top_level = top_level_count if top_level_count is not None else None
    total_flat = len(flat)

    return CommentStats(
        total_flat=total_flat,
        top_level_count=top_level,
        reply_count=reply_count if reply_count else None,
        with_published_at=with_ts,
        volume_by_day=volume,
        like_buckets=like_buckets,
        top_authors=aggregates,
    )


def extract_keywords(flat: list[dict[str, Any]], *, top_n: int = 40, min_len: int = 3) -> list[KeywordTerm]:
    counts: Counter[str] = Counter()
    for r in flat:
        text = r.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        for m in _WORD_RE.finditer(text.lower()):
            w = m.group(0).lower()
            if len(w) < min_len or w in _STOPWORDS:
                continue
            counts[w] += 1
    return [KeywordTerm(term=w, count=c) for w, c in counts.most_common(top_n)]


def comment_corpus_fingerprint(flat: list[dict[str, Any]]) -> str:
    """Stable SHA256 hex digest over comment ids and text for cache invalidation."""

    import hashlib

    parts: list[str] = []
    for r in sorted(flat, key=lambda x: str(x.get("comment_id") or "")):
        cid = str(r.get("comment_id") or "")
        txt = str(r.get("text") or "")
        parts.append(f"{cid}\t{txt}")
    blob = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
