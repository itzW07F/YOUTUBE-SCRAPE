"""SQLite persistence for analytics RAG chunks + float vectors (stdlib only)."""

from __future__ import annotations

import math
import sqlite3
import struct
from pathlib import Path
from typing import Any


def _pack_vec(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_vec(blob: bytes) -> list[float]:
    if not blob or len(blob) % 4 != 0:
        return []
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    sa = 0.0
    sb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        sa += x * x
        sb += y * y
    if sa <= 0.0 or sb <= 0.0:
        return 0.0
    return dot / (math.sqrt(sa) * math.sqrt(sb))


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_kind TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            body TEXT NOT NULL,
            dim INTEGER NOT NULL,
            vec BLOB NOT NULL
        )
        """
    )
    conn.commit()


def clear_and_insert(
    db_path: Path,
    rows: list[tuple[str, str, str, list[float]]],
) -> None:
    """Replace all rows. Each row: (source_kind, source_ref, body, embedding)."""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DROP TABLE IF EXISTS chunks")
        init_db(conn)
        for kind, ref, body, vec in rows:
            if not vec:
                continue
            dim = len(vec)
            conn.execute(
                "INSERT INTO chunks (source_kind, source_ref, body, dim, vec) VALUES (?, ?, ?, ?, ?)",
                (kind, ref, body, dim, _pack_vec(vec)),
            )
        conn.commit()
    finally:
        conn.close()


def clear_and_insert_with_progress(
    db_path: Path,
    rows: list[tuple[str, str, str, list[float]]],
    progress_callback: callable | None = None,
    progress_interval: int = 100,
) -> None:
    """Replace all rows with progress callbacks for long-running inserts.

    Args:
        db_path: Path to SQLite database
        rows: List of (source_kind, source_ref, body, embedding) tuples
        progress_callback: Optional callback(chunks_written, total_chunks) -> None
        progress_interval: How often to call progress callback (every N rows)
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DROP TABLE IF EXISTS chunks")
        init_db(conn)

        total = len(rows)
        written = 0

        for kind, ref, body, vec in rows:
            if not vec:
                continue
            dim = len(vec)
            conn.execute(
                "INSERT INTO chunks (source_kind, source_ref, body, dim, vec) VALUES (?, ?, ?, ?, ?)",
                (kind, ref, body, dim, _pack_vec(vec)),
            )
            written += 1

            if progress_callback and written % progress_interval == 0:
                progress_callback(written, total)

        conn.commit()

        if progress_callback:
            progress_callback(written, total)
    finally:
        conn.close()


def load_all_chunks(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.is_file():
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "SELECT source_kind, source_ref, body, dim, vec FROM chunks ORDER BY id ASC",
        )
        out: list[dict[str, Any]] = []
        for kind, ref, body, dim, blob in cur.fetchall():
            vec = _unpack_vec(blob)
            if len(vec) != int(dim):
                continue
            out.append(
                {
                    "source_kind": str(kind),
                    "source_ref": str(ref),
                    "body": str(body),
                    "embedding": vec,
                },
            )
        return out
    finally:
        conn.close()


def _source_boost(query_lower: str, source_kind: str) -> float:
    """Boost score based on query-source relevance."""
    boosts = {
        "comment": ["comment", "comments", "said", "people", "users", "viewers", "replies", "discuss"],
        "transcript": ["transcript", "video", "says", "said", "timestamp", "minute", "seconds", "recording"],
        "video": ["video", "metadata", "title", "channel", "views", "likes", "upload", "duration"],
        "metadata_history": ["history", "trend", "over time", "gained", "increased", "decreased"],
        "thumbnails": ["thumbnail", "thumbnails", "image", "picture", "preview"],
    }
    keywords = boosts.get(source_kind, [])
    for kw in keywords:
        if kw in query_lower:
            return 0.15  # Boost by 0.15 (on top of 0-1 cosine)
    return 0.0


def top_cosine(
    query: list[float],
    chunks: list[dict[str, Any]],
    k: int,
    query_text: str = "",
) -> list[tuple[str, str, str, float]]:
    """Return up to ``k`` tuples (kind, ref, body, score) sorted by hybrid relevance."""

    if k < 1 or not query or not chunks:
        return []
    query_lower = query_text.lower()
    scored: list[tuple[str, str, str, float]] = []
    for row in chunks:
        emb = row.get("embedding")
        if not isinstance(emb, list) or not emb:
            continue
        cosine = cosine_similarity(query, emb)
        boost = _source_boost(query_lower, row["source_kind"])
        hybrid_score = cosine + boost
        scored.append((row["source_kind"], row["source_ref"], row["body"], hybrid_score))
    scored.sort(key=lambda x: x[3], reverse=True)
    return scored[:k]
