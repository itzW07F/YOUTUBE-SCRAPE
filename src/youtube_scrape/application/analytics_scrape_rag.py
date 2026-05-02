"""Per-folder SQLite + Ollama embeddings for analytics chat (optional RAG)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import sqlite3
import struct
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx

from youtube_scrape.adapters.analytics_artifacts import envelope_inner_data, read_json_file, read_metadata_history_jsonl
from youtube_scrape.adapters.ollama_client import OllamaHttpError, ollama_embed_prompt
from youtube_scrape.application.analytics_rag_store import clear_and_insert, init_db, load_all_chunks, top_cosine
from youtube_scrape.application.analytics_scrape_context_pack import ScrapeContextPack, build_scrape_mini_header
from youtube_scrape.domain.analytics_aggregate import flatten_comment_nodes
from youtube_scrape.settings import Settings

log = logging.getLogger(__name__)

# Bumped when stored vectors are incompatible with prior builds (embedding API / vector layout changed).
RAG_SCHEMA_VERSION = "2"
RAG_DIRNAME = ".analytics_rag"
MANIFEST_NAME = "manifest.json"
DB_NAME = "chunks.sqlite3"

TRACKED_ARTIFACTS: tuple[str, ...] = (
    "video.json",
    "comments.json",
    "metadata_history.jsonl",
    "thumbnails.json",
    "transcript.txt",
    "transcript.vtt",
    "transcript.json",
)

_MAX_COMMENT_CHUNKS = 4000
_TRANSCRIPT_BATCH_CHARS = 1600
_JSON_TRANSCRIPT_CAP = 14_000
_VIDEO_JSON_CHUNK_CAP = 12_000
_HISTORY_CAP = 12_000
_THUMBS_CAP = 8000


def rag_dir(output_dir: Path) -> Path:
    return output_dir / RAG_DIRNAME


def rag_manifest_path(output_dir: Path) -> Path:
    return rag_dir(output_dir) / MANIFEST_NAME


def rag_db_path(output_dir: Path) -> Path:
    return rag_dir(output_dir) / DB_NAME


def compute_source_fingerprints(output_dir: Path) -> dict[str, str]:
    import hashlib

    out: dict[str, str] = {}
    for name in TRACKED_ARTIFACTS:
        p = output_dir / name
        if not p.is_file():
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        out[name] = hashlib.sha256(data).hexdigest()
    return dict(sorted(out.items()))


def _video_chunk(output_dir: Path, warnings: list[str]) -> tuple[str, str, str] | None:
    env = read_json_file(output_dir / "video.json")
    if env is None:
        return None
    inner = envelope_inner_data(env)
    try:
        blob = json.dumps(inner, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        warnings.append("video.json could not be serialized for RAG; skipped.")
        return None
    if len(blob) > _VIDEO_JSON_CHUNK_CAP:
        blob = blob[:_VIDEO_JSON_CHUNK_CAP] + "\n… [truncated for RAG]"
    return ("video", "video.json", blob)


def _pick_transcript_path(output_dir: Path) -> Path | None:
    for suf in ("txt", "vtt", "json"):
        p = output_dir / f"transcript.{suf}"
        if p.is_file():
            return p
    return None


def _normalize_transcript_lines(raw: str, filename: str) -> list[str]:
    lower = filename.lower()
    if lower.endswith(".vtt"):
        out: list[str] = []
        for ln in raw.splitlines():
            s = ln.strip()
            if not s or s.startswith("WEBVTT") or s.startswith("NOTE") or "-->" in s:
                continue
            plain = re.sub(r"<[^>]+>", "", ln).strip()
            if plain:
                out.append(plain)
        return out
    if lower.endswith(".json"):
        return [raw] if raw.strip() else []
    return [ln.strip() for ln in raw.splitlines() if ln.strip()]


def _batch_transcript_lines(
    lines: list[str],
    *,
    ref_file: str,
    max_chars: int,
) -> list[tuple[str, str, str]]:
    if not lines:
        return []
    chunks: list[tuple[str, str, str]] = []
    i = 0
    n = len(lines)
    while i < n:
        buf: list[str] = []
        size = 0
        start = i
        while i < n:
            ln = lines[i]
            add = len(ln) + (1 if buf else 0)
            if buf and size + add > max_chars:
                break
            buf.append(ln)
            size += add
            i += 1
        if buf:
            ref = f"{ref_file}:L{start + 1}-L{i}"
            chunks.append(("transcript", ref, "\n".join(buf)))
    return chunks


def _transcript_chunks(path: Path, warnings: list[str]) -> list[tuple[str, str, str]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        warnings.append(f"Could not read {path.name} for RAG; skipped.")
        return []
    lines = _normalize_transcript_lines(raw, path.name)
    if not lines:
        return []
    if path.suffix.lower() == ".json":
        body = lines[0]
        if len(body) > _JSON_TRANSCRIPT_CAP:
            body = body[:_JSON_TRANSCRIPT_CAP] + "…"
        return [("transcript", path.name, body)]
    return _batch_transcript_lines(lines, ref_file=path.name, max_chars=_TRANSCRIPT_BATCH_CHARS)


def _comment_chunks(output_dir: Path, warnings: list[str]) -> list[tuple[str, str, str]]:
    env = read_json_file(output_dir / "comments.json")
    if env is None:
        return []
    data = envelope_inner_data(env)
    raw = data.get("comments")
    if not isinstance(raw, list):
        return []
    flat = flatten_comment_nodes(raw)
    if len(flat) > _MAX_COMMENT_CHUNKS:
        warnings.append(f"RAG indexed first {_MAX_COMMENT_CHUNKS} of {len(flat)} comments.")
        flat = flat[:_MAX_COMMENT_CHUNKS]
    out: list[tuple[str, str, str]] = []
    for row in flat:
        if not isinstance(row, dict):
            continue
        cid = row.get("comment_id") or row.get("id") or ""
        text = row.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        body = text.strip()[:6000]
        ref = f"id={cid}" if cid else "row"
        out.append(("comment", ref, body))
    return out


def _history_chunk(output_dir: Path) -> tuple[str, str, str] | None:
    lines = read_metadata_history_jsonl(output_dir / "metadata_history.jsonl")
    if not lines:
        return None
    txt = "\n".join(json.dumps(row, ensure_ascii=False) for row in lines)
    if len(txt) > _HISTORY_CAP:
        txt = txt[:_HISTORY_CAP] + "\n… [truncated]"
    return ("metadata_history", "metadata_history.jsonl", txt)


def _thumbs_chunk(output_dir: Path) -> tuple[str, str, str] | None:
    thumbs = read_json_file(output_dir / "thumbnails.json")
    if thumbs is None:
        return None
    try:
        txt = json.dumps(thumbs, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return None
    if len(txt) > _THUMBS_CAP:
        txt = txt[:_THUMBS_CAP] + "\n… [truncated]"
    return ("thumbnails", "thumbnails.json", txt)


def collect_rag_chunks(output_dir: Path, warnings: list[str]) -> list[tuple[str, str, str]]:
    """Collect all RAG chunks including video, transcript, comments, history, thumbnails.

    Used by analytics chat for full context retrieval.
    """
    out: list[tuple[str, str, str]] = []
    vc = _video_chunk(output_dir, warnings)
    if vc:
        out.append(vc)
    tp = _pick_transcript_path(output_dir)
    if tp is not None:
        out.extend(_transcript_chunks(tp, warnings))
    out.extend(_comment_chunks(output_dir, warnings))
    hist = _history_chunk(output_dir)
    if hist:
        out.append(hist)
    th = _thumbs_chunk(output_dir)
    if th:
        out.append(th)
    return [x for x in out if x[2].strip()]


def collect_vector_db_chunks(output_dir: Path, warnings: list[str]) -> list[tuple[str, str, str]]:
    """Collect only video and comment chunks for Vector DB indexing.

    This is a focused subset for the Vector DB feature, skipping transcripts,
    thumbnails, and metadata history to reduce noise and build time.
    """
    out: list[tuple[str, str, str]] = []
    vc = _video_chunk(output_dir, warnings)
    if vc:
        out.append(vc)
    out.extend(_comment_chunks(output_dir, warnings))
    return [x for x in out if x[2].strip()]


def _read_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _manifest_matches(manifest: dict[str, Any], *, sources: dict[str, str], embed_model: str) -> bool:
    from youtube_scrape.adapters.ollama_client import model_matches_installed
    if manifest.get("rag_schema_version") != RAG_SCHEMA_VERSION:
        return False
    manifest_embed_model = manifest.get("embed_model")
    if not isinstance(manifest_embed_model, str) or not model_matches_installed(embed_model, [manifest_embed_model]):
        return False
    msrc = manifest.get("sources")
    if not isinstance(msrc, dict):
        return False
    norm = {str(k): str(v) for k, v in msrc.items()}
    return norm == sources


def _purge_rag_artifacts(output_dir: Path) -> None:
    for name in (DB_NAME, MANIFEST_NAME):
        p = rag_dir(output_dir) / name
        with contextlib.suppress(OSError):
            p.unlink(missing_ok=True)


async def ensure_rag_index(
    output_dir: Path,
    *,
    embed_model: str,
    base_url: str,
    timeout_s: float,
    warnings: list[str],
) -> tuple[bool, int]:
    """Ensure SQLite index exists and matches artifact fingerprints.

    Returns ``(reused_existing, build_wall_ms)`` where ``build_wall_ms`` is 0 when reused.
    """

    log.info(
        "analytics_rag_ensure_index_start",
        extra={
            "folder": output_dir.name,
            "embed_model": embed_model,
            "rag_dir": str(rag_dir(output_dir)),
        },
    )
    
    sources = compute_source_fingerprints(output_dir)
    log.info(
        "analytics_rag_source_fingerprints",
        extra={
            "folder": output_dir.name,
            "tracked_files": len(sources),
            "files": list(sources.keys()),
        },
    )
    
    mp = rag_manifest_path(output_dir)
    dp = rag_db_path(output_dir)
    man = _read_manifest(mp)
    
    if man is not None and dp.is_file() and _manifest_matches(man, sources=sources, embed_model=embed_model):
        log.info(
            "analytics_rag_index_reused",
            extra={
                "folder": output_dir.name,
                "chunks": man.get("chunk_count"),
                "embed_dim": man.get("embed_dim"),
            },
        )
        return True, 0
    
    if man is None:
        log.info("analytics_rag_no_manifest", extra={"folder": output_dir.name})
    elif not dp.is_file():
        log.info("analytics_rag_db_missing", extra={"folder": output_dir.name})
    else:
        log.info(
            "analytics_rag_manifest_mismatch",
            extra={
                "folder": output_dir.name,
                "manifest_model": man.get("embed_model"),
                "current_model": embed_model,
            },
        )

    t0 = time.perf_counter()
    chunks_meta = collect_rag_chunks(output_dir, warnings)
    log.info(
        "analytics_rag_chunks_collected",
        extra={
            "folder": output_dir.name,
            "chunk_count": len(chunks_meta),
            "by_source": {k: len([c for c in chunks_meta if c[0] == k]) for k in set(c[0] for c in chunks_meta)},
        },
    )
    texts = [c[2] for c in chunks_meta]
    if not texts:
        _purge_rag_artifacts(output_dir)
        log.warning("analytics_rag_skip_empty_corpus", extra={"folder": output_dir.name})
        warnings.append("No text chunks found for indexing (missing scrape files?)")
        return False, int((time.perf_counter() - t0) * 1000)

    embed_timeout = min(120.0, max(15.0, timeout_s))
    t = httpx.Timeout(timeout_s, connect=min(15.0, timeout_s))
    sem = asyncio.Semaphore(6)

    async def one_embed(text: str, client: httpx.AsyncClient) -> list[float]:
        async with sem:
            return await ollama_embed_prompt(
                base_url=base_url,
                model=embed_model,
                prompt=text,
                timeout_s=embed_timeout,
                client=client,
            )

    rows: list[tuple[str, str, str, list[float]]] = []
    dim = 0
    log.info(
        "analytics_rag_embedding_start",
        extra={
            "folder": output_dir.name,
            "text_count": len(texts),
            "embed_model": embed_model,
            "base_url": base_url,
        },
    )
    try:
        async with httpx.AsyncClient(timeout=t) as client:
            vecs = await asyncio.gather(*[one_embed(tx, client) for tx in texts])
        log.info(
            "analytics_rag_embedding_complete",
            extra={
                "folder": output_dir.name,
                "vectors_received": len(vecs),
                "sample_dim": len(vecs[0]) if vecs else 0,
            },
        )
    except (OllamaHttpError, httpx.HTTPError, OSError) as exc:
        log.warning(
            "analytics_rag_index_embed_failed",
            extra={
                "error": str(exc)[:400],
                "error_type": type(exc).__name__,
                "folder": output_dir.name,
                "embed_model": embed_model,
            },
        )
        error_msg = str(exc).lower()
        if "failed to load" in error_msg or "resource" in error_msg:
            warnings.append(
                f"RAG index build failed: embedding model '{embed_model}' exists but failed to load. "
                f"This may be due to resource limitations on the Ollama server ({base_url}). "
                f"Try: 1) Restarting Ollama, 2) Using a smaller model, 3) Checking Ollama logs."
            )
        else:
            warnings.append(f"RAG index build failed ({type(exc).__name__}); falling back to metadata-only.")
        return False, int((time.perf_counter() - t0) * 1000)

    for (kind, ref, body), vec in zip(chunks_meta, vecs, strict=True):
        if not vec:
            continue
        dim = len(vec)
        rows.append((kind, ref, body, vec))

    if not rows:
        _purge_rag_artifacts(output_dir)
        warnings.append("RAG index produced no embeddings.")
        return False, int((time.perf_counter() - t0) * 1000)

    rdir = rag_dir(output_dir)
    rdir.mkdir(parents=True, exist_ok=True)
    clear_and_insert(dp, rows)
    manifest_obj = {
        "rag_schema_version": RAG_SCHEMA_VERSION,
        "sources": sources,
        "embed_model": embed_model,
        "chunk_count": len(rows),
        "embed_dim": dim,
    }
    mp.write_text(json.dumps(manifest_obj, indent=2), encoding="utf-8")
    build_ms = int((time.perf_counter() - t0) * 1000)
    log.info(
        "analytics_rag_index_built",
        extra={"folder": output_dir.name, "chunks": len(rows), "build_ms": build_ms},
    )
    return False, build_ms


async def retrieve_rag_excerpts(
    output_dir: Path,
    *,
    user_query: str,
    embed_model: str,
    base_url: str,
    top_k: int,
    timeout_s: float,
    warnings: list[str],
) -> tuple[list[tuple[str, str, str]], int, int]:
    """Return ``(excerpts, index_build_ms, query_embed_ms)``."""

    log.info(
        "analytics_rag_retrieve_start",
        extra={
            "folder": output_dir.name,
            "query_preview": user_query[:60] if user_query else "",
            "embed_model": embed_model,
            "top_k": top_k,
        },
    )
    
    _reused, index_build_ms = await ensure_rag_index(
        output_dir,
        embed_model=embed_model,
        base_url=base_url,
        timeout_s=timeout_s,
        warnings=warnings,
    )
    dp = rag_db_path(output_dir)
    if not dp.is_file():
        log.warning(
            "analytics_rag_db_not_found",
            extra={
                "folder": output_dir.name,
                "db_path": str(dp),
                "index_build_ms": index_build_ms,
            },
        )
        warnings.append("RAG index database not found; using metadata-only fallback.")
        return [], index_build_ms, 0
    
    chunks = load_all_chunks(dp)
    log.info(
        "analytics_rag_db_loaded",
        extra={
            "folder": output_dir.name,
            "chunks_loaded": len(chunks),
            "db_path": str(dp),
        },
    )
    if not chunks:
        log.warning("analytics_rag_db_empty", extra={"folder": output_dir.name})
        warnings.append("RAG index is empty; using metadata-only fallback.")
        return [], index_build_ms, 0
    qt = user_query.strip()
    if not qt:
        return [], index_build_ms, 0
    t0 = time.perf_counter()
    log.info(
        "analytics_rag_query_embedding_start",
        extra={
            "folder": output_dir.name,
            "query_preview": qt[:60] if qt else "",
            "embed_model": embed_model,
        },
    )
    try:
        qvec = await ollama_embed_prompt(
            base_url=base_url,
            model=embed_model,
            prompt=qt,
            timeout_s=min(120.0, max(15.0, timeout_s)),
        )
        log.info(
            "analytics_rag_query_embedding_success",
            extra={
                "folder": output_dir.name,
                "vector_dim": len(qvec),
            },
        )
    except (OllamaHttpError, httpx.HTTPError, OSError) as exc:
        log.warning(
            "analytics_rag_query_embed_failed",
            extra={
                "error": str(exc)[:400],
                "error_type": type(exc).__name__,
                "folder": output_dir.name,
                "embed_model": embed_model,
            },
        )
        # Provide specific guidance based on error type
        error_msg = str(exc).lower()
        # Distinguish between "model not found" (404/not available) vs "model failed to load" (resource/loading issue)
        is_model_not_found = (
            "404" in error_msg or 
            ("not available" in error_msg and "locally" in error_msg) or
            ("not found" in error_msg and "pull" in error_msg)
        )
        is_model_load_failure = "failed to load" in error_msg or "resource" in error_msg

        if is_model_not_found:
            warnings.append(
                f"RAG query embedding failed: embedding model '{embed_model}' not found in Ollama. "
                f"Run 'ollama pull {embed_model}' on your Ollama server ({base_url}), then try again."
            )
        elif is_model_load_failure:
            warnings.append(
                f"RAG query embedding failed: model '{embed_model}' exists but failed to load. "
                f"This may be due to resource limitations on the Ollama server. "
                f"Try: 1) Restarting Ollama, 2) Using a smaller embedding model, 3) Checking Ollama server logs."
            )
        else:
            warnings.append(f"RAG query embedding failed ({type(exc).__name__}); falling back to metadata-only.")
        return [], index_build_ms, int((time.perf_counter() - t0) * 1000)

    embed_ms = int((time.perf_counter() - t0) * 1000)
    tops = top_cosine(qvec, chunks, top_k, query_text=qt)
    out = [(a, b, c) for a, b, c, _s in tops]
    log.info(
        "analytics_rag_retrieval_complete",
        extra={
            "folder": output_dir.name,
            "query_preview": qt[:60] if qt else "",
            "chunks_returned": len(out),
            "top_scores": [round(s, 3) for _, _, _, s in tops[:3]] if tops else [],
            "index_build_ms": index_build_ms,
            "embed_ms": embed_ms,
        },
    )
    return out, index_build_ms, embed_ms


def build_hybrid_context_text(
    output_dir: Path,
    retrieved: list[tuple[str, str, str]],
    *,
    max_chars: int,
    warnings: list[str],
) -> str:
    mini_warn: list[str] = []
    mini = build_scrape_mini_header(output_dir, mini_warn)
    warnings.extend(mini_warn)

    opener = (
        "# Scraped data (retrieval-assisted)\n\n"
        "Ground answers only in the metadata header and the labeled excerpts below.\n\n"
        "## metadata_header\n\n"
        f"{mini}\n\n"
        "## retrieved_excerpts\n\n"
    )
    parts: list[str] = [opener]
    used = len(opener)
    for kind, ref, body in retrieved:
        block = f"### excerpt:{kind}:{ref}\n\n{body.strip()}\n\n"
        if used + len(block) > max_chars:
            warnings.append("Some retrieved excerpts omitted — RAG context char budget exhausted.")
            break
        parts.append(block)
        used += len(block)
    text = "".join(parts).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 64] + "\n… [truncated]"
        warnings.append("RAG context truncated to analytics_rag_max_context_chars.")
    return text


def analytics_rag_eligible(settings: Settings) -> bool:
    return bool(
        settings.analytics_rag_enabled
        and settings.analytics_llm_provider == "ollama"
        and settings.analytics_ollama_enabled
    )


def _build_metadata_only_context(
    output_dir: Path,
    warnings: list[str],
    max_chars: int,
) -> str:
    """Build minimal context with just metadata header for fallback."""
    mini_warn: list[str] = []
    mini = build_scrape_mini_header(output_dir, mini_warn)
    warnings.extend(mini_warn)
    text = (
        "# Scraped data (metadata-only fallback)\n\n"
        "Ground answers only in the metadata below. Full excerpt retrieval failed; "
        "answer based on available metadata only.\n\n"
        "## metadata_header\n\n"
        f"{mini}\n"
    )
    if len(text) > max_chars:
        text = text[: max_chars - 32] + "\n… [truncated]"
    return text


async def try_resolve_hybrid_context_pack(
    output_dir: Path,
    *,
    user_query: str,
    settings: Settings,
    rag_top_k: int | None = None,
) -> tuple[ScrapeContextPack | None, dict[str, Any]]:
    """Return hybrid pack or ``None`` (caller uses legacy ``build_scrape_context_pack``).

    Second value carries diagnostics for ``AnalyticsChatResponse`` (subset may be empty).

    ``rag_top_k`` overrides ``settings.analytics_rag_top_k`` when set (macro brief uses a higher floor).
    """

    empty_diag: dict[str, Any] = {
        "analytics_rag_mode": None,
        "analytics_rag_chunks_used": None,
        "analytics_rag_index_build_ms": None,
        "analytics_rag_embed_ms": None,
    }
    
    # Debug logging to help troubleshoot
    log.info(
        "analytics_rag_check_eligible",
        extra={
            "rag_enabled": settings.analytics_rag_enabled,
            "provider": settings.analytics_llm_provider,
            "ollama_enabled": settings.analytics_ollama_enabled,
            "folder": output_dir.name,
        },
    )
    
    if not analytics_rag_eligible(settings):
        log.info(
            "analytics_rag_not_eligible",
            extra={
                "folder": output_dir.name,
                "rag_enabled": settings.analytics_rag_enabled,
                "provider": settings.analytics_llm_provider,
                "ollama_enabled": settings.analytics_ollama_enabled,
            },
        )
        return None, empty_diag

    effective_top_k = rag_top_k if rag_top_k is not None else settings.analytics_rag_top_k
    log.info(
        "analytics_rag_eligible_and_starting",
        extra={
            "folder": output_dir.name,
            "embed_model": settings.ollama_embed_model,
            "top_k": effective_top_k,
            "top_k_override": rag_top_k is not None,
        },
    )

    # Verify embedding model exists before attempting RAG
    embed_model = settings.ollama_embed_model.strip() or "nomic-embed-text"
    try:
        from youtube_scrape.adapters.ollama_client import ollama_list_model_names, model_matches_installed
        available_models = await ollama_list_model_names(base_url=settings.ollama_base_url, timeout_s=10.0)
        if not model_matches_installed(embed_model, available_models):
            log.warning(
                "analytics_rag_embed_model_missing",
                extra={
                    "folder": output_dir.name,
                    "embed_model": embed_model,
                    "available_models": available_models[:10],
                },
            )
            meta_text = _build_metadata_only_context(
                output_dir, [f"Embedding model '{embed_model}' not found. Run 'ollama pull {embed_model}'"], settings.analytics_rag_max_context_chars
            )
            pack = ScrapeContextPack(text=meta_text, warnings=[
                f"RAG requires embedding model '{embed_model}' which is not available in Ollama.",
                f"Please run: ollama pull {embed_model}",
                "Falling back to metadata-only context for this request.",
            ])
            return pack, {
                **empty_diag,
                "analytics_rag_mode": "fallback_meta",
                "analytics_rag_chunks_used": 0,
                "analytics_rag_index_build_ms": 0,
                "analytics_rag_embed_ms": 0,
                "_embed_model_missing": True,
            }
    except Exception as exc:
        log.warning(
            "analytics_rag_model_check_failed",
            extra={"folder": output_dir.name, "error": str(exc)[:200]},
        )
        # Continue anyway - let the actual embedding call fail with proper error

    local_warnings: list[str] = []
    try:
        retrieved, index_build_ms, embed_ms = await retrieve_rag_excerpts(
            output_dir,
            user_query=user_query,
            embed_model=settings.ollama_embed_model.strip() or "nomic-embed-text",
            base_url=settings.ollama_base_url,
            top_k=effective_top_k,
            timeout_s=settings.ollama_timeout_s,
            warnings=local_warnings,
        )
    except Exception as exc:
        log.warning(
            "analytics_rag_unexpected_error",
            extra={
                "error": str(exc)[:500],
                "error_type": type(exc).__name__,
                "folder": output_dir.name,
            },
        )
        # Return metadata-only fallback instead of None to avoid full context dump
        meta_text = _build_metadata_only_context(
            output_dir, local_warnings, settings.analytics_rag_max_context_chars
        )
        local_warnings.append(f"RAG failed ({type(exc).__name__}); using metadata-only fallback.")
        pack = ScrapeContextPack(text=meta_text, warnings=local_warnings)
        log.info(
            "analytics_rag_fallback_meta",
            extra={
                "folder": output_dir.name,
                "final_chars": len(meta_text),
                "reason": "exception",
                "error_type": type(exc).__name__,
            },
        )
        return pack, {
            **empty_diag,
            "analytics_rag_mode": "fallback_meta",
            "analytics_rag_index_build_ms": 0,
            "analytics_rag_embed_ms": 0,
            "_failure": str(exc),
        }

    if not retrieved:
        # Metadata-only fallback instead of falling back to full bundle
        log.warning(
            "analytics_rag_no_results",
            extra={
                "folder": output_dir.name,
                "query_preview": user_query[:60] if user_query else "",
                "index_build_ms": index_build_ms,
            },
        )
        meta_text = _build_metadata_only_context(
            output_dir, local_warnings, settings.analytics_rag_max_context_chars
        )
        if not local_warnings:
            local_warnings.append("RAG returned no excerpts; using metadata-only fallback.")
        pack = ScrapeContextPack(text=meta_text, warnings=local_warnings)
        log.info(
            "analytics_rag_fallback_meta",
            extra={
                "folder": output_dir.name,
                "final_chars": len(meta_text),
                "reason": "no_results",
            },
        )
        return pack, {
            **empty_diag,
            "analytics_rag_mode": "fallback_meta",
            "analytics_rag_chunks_used": 0,
            "analytics_rag_index_build_ms": index_build_ms,
            "analytics_rag_embed_ms": embed_ms,
        }

    text = build_hybrid_context_text(
        output_dir,
        retrieved,
        max_chars=settings.analytics_rag_max_context_chars,
        warnings=local_warnings,
    )
    mode: Literal["hybrid"] = "hybrid"
    log.info(
        "analytics_rag_hybrid_success",
        extra={
            "folder": output_dir.name,
            "final_chars": len(text),
            "chunks_used": len(retrieved),
            "mode": mode,
        },
    )
    pack = ScrapeContextPack(text=text, warnings=local_warnings)
    return pack, {
        "analytics_rag_mode": mode,
        "analytics_rag_chunks_used": len(retrieved),
        "analytics_rag_index_build_ms": index_build_ms,
        "analytics_rag_embed_ms": embed_ms,
    }


def _detect_available_sources(output_dir: Path) -> tuple[list[str], list[str]]:
    """Return (eligible_sources, missing_sources) based on tracked artifacts."""
    available: list[str] = []
    missing: list[str] = []
    for name in TRACKED_ARTIFACTS:
        p = output_dir / name
        if p.is_file():
            available.append(name)
        else:
            missing.append(name)
    return available, missing


def _detect_vector_db_sources(output_dir: Path) -> tuple[list[str], list[str]]:
    """Return (eligible_sources, missing_sources) for Vector DB (video + comments only)."""
    vector_db_artifacts = ("video.json", "comments.json")
    available: list[str] = []
    missing: list[str] = []
    for name in vector_db_artifacts:
        p = output_dir / name
        if p.is_file():
            available.append(name)
        else:
            missing.append(name)
    return available, missing


def _has_download_only(output_dir: Path) -> bool:
    """Check if folder has only download artifacts (yt-dlp only, no scrape data)."""
    has_download = (output_dir / "download").is_dir()
    has_scrape_data = any((output_dir / name).is_file() for name in TRACKED_ARTIFACTS)
    return has_download and not has_scrape_data


def get_rag_status(output_dir: Path) -> dict[str, Any]:
    """Check RAG vectorization status for an output folder.

    Returns a dict matching RagStatusPayload structure.
    """
    mp = rag_manifest_path(output_dir)
    dp = rag_db_path(output_dir)

    # Only check for video.json and comments.json for Vector DB eligibility
    eligible_sources, missing_sources = _detect_vector_db_sources(output_dir)
    has_download_only_flag = _has_download_only(output_dir)

    is_vectorized = dp.is_file() and mp.is_file()
    chunk_count = 0
    embed_model: str | None = None
    embed_dim: int | None = None
    last_updated: str | None = None

    if is_vectorized and mp.is_file():
        man = _read_manifest(mp)
        if man:
            chunk_count = man.get("chunk_count", 0)
            embed_model = man.get("embed_model")
            embed_dim = man.get("embed_dim")
            # Try to get mtime from manifest file as last_updated
            try:
                stat = mp.stat()
                last_updated = datetime.utcfromtimestamp(stat.st_mtime).isoformat()
            except OSError:
                pass

    return {
        "output_dir": str(output_dir),
        "is_vectorized": is_vectorized,
        "chunk_count": chunk_count,
        "embed_model": embed_model,
        "embed_dim": embed_dim,
        "last_updated": last_updated,
        "eligible_sources": eligible_sources,
        "missing_sources": missing_sources,
        "has_download_only": has_download_only_flag,
    }


async def build_rag_index_with_progress(
    output_dir: Path,
    *,
    embed_model: str,
    base_url: str,
    timeout_s: float,
    job_id: str,
    manager: Any,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Build RAG index with WebSocket progress updates.

    This wraps ensure_rag_index with progress callbacks for GUI feedback.
    Returns a status dict with build results.
    """
    from datetime import datetime

    log.info(
        "analytics_rag_build_start",
        extra={
            "folder": output_dir.name,
            "job_id": job_id,
            "embed_model": embed_model,
            "force_refresh": force_refresh,
        },
    )

    await manager.send_status(job_id, "running", {"message": "Starting RAG index build..."})
    await manager.send_progress(job_id, 5, "Analyzing source files...")

    warnings: list[str] = []

    # Check if already up-to-date unless forcing refresh
    if not force_refresh:
        sources = compute_source_fingerprints(output_dir)
        mp = rag_manifest_path(output_dir)
        dp = rag_db_path(output_dir)
        man = _read_manifest(mp)
        if man is not None and dp.is_file() and _manifest_matches(man, sources=sources, embed_model=embed_model):
            await manager.send_progress(job_id, 100, "Index already up to date")
            await manager.send_status(job_id, "completed", {"message": "Index already up to date", "reused": True})
            return {
                "success": True,
                "reused": True,
                "chunk_count": man.get("chunk_count", 0),
                "embed_model": embed_model,
            }

    await manager.send_progress(job_id, 10, "Collecting video and comment chunks...")

    # Collect chunks (focused subset: video + comments only, skipping thumbnails/transcripts)
    chunks_meta = collect_vector_db_chunks(output_dir, warnings)
    total_chunks = len(chunks_meta)

    if not chunks_meta:
        await manager.send_progress(job_id, 100, "No text chunks found")
        await manager.send_status(job_id, "failed", {"message": "No text chunks found for indexing", "warnings": warnings})
        return {
            "success": False,
            "error": "No text chunks found for indexing",
            "warnings": warnings,
        }

    await manager.send_progress(job_id, 20, f"Collected {total_chunks} chunks, generating embeddings...")

    texts = [c[2] for c in chunks_meta]
    embed_timeout = min(120.0, max(15.0, timeout_s))
    t = httpx.Timeout(timeout_s, connect=min(15.0, timeout_s))
    sem = asyncio.Semaphore(6)

    # Track embedding progress - 20% to 80% range
    embed_start_progress = 20
    embed_end_progress = 80
    embed_range = embed_end_progress - embed_start_progress
    last_reported_progress = embed_start_progress

    async def one_embed_with_progress(text: str, idx: int, client: httpx.AsyncClient) -> list[float]:
        async with sem:
            try:
                vec = await ollama_embed_prompt(
                    base_url=base_url,
                    model=embed_model,
                    prompt=text,
                    timeout_s=embed_timeout,
                    client=client,
                )
                # Calculate progress (20-80% range)
                progress = embed_start_progress + int(((idx + 1) / total_chunks) * embed_range)

                # Only send update if progress changed significantly (every 2%)
                nonlocal last_reported_progress
                if progress >= last_reported_progress + 2 or idx == total_chunks - 1:
                    last_reported_progress = progress
                    await manager.send_progress(job_id, progress, f"Embedding chunk {idx + 1} of {total_chunks}...")
                return vec
            except Exception as exc:
                log.warning(
                    "analytics_rag_build_embed_chunk_failed",
                    extra={
                        "folder": output_dir.name,
                        "job_id": job_id,
                        "chunk_idx": idx,
                        "error": str(exc)[:200],
                    },
                )
                return []

    rows: list[tuple[str, str, str, list[float]]] = []
    dim = 0

    try:
        async with httpx.AsyncClient(timeout=t) as client:
            vecs = await asyncio.gather(*[
                one_embed_with_progress(tx, i, client) for i, tx in enumerate(texts)
            ])
    except (OllamaHttpError, httpx.HTTPError, OSError) as exc:
        log.warning(
            "analytics_rag_build_embed_failed",
            extra={
                "error": str(exc)[:400],
                "error_type": type(exc).__name__,
                "folder": output_dir.name,
                "job_id": job_id,
                "embed_model": embed_model,
            },
        )
        await manager.send_progress(job_id, 100, f"Embedding failed: {exc}")
        await manager.send_status(job_id, "failed", {"message": f"Embedding failed: {exc}"})
        return {
            "success": False,
            "error": f"RAG index build failed ({type(exc).__name__}): {exc}",
        }

    for (kind, ref, body), vec in zip(chunks_meta, vecs, strict=True):
        if not vec:
            continue
        dim = len(vec)
        rows.append((kind, ref, body, vec))

    if not rows:
        await manager.send_progress(job_id, 100, "No valid embeddings generated")
        await manager.send_status(job_id, "failed", {"message": "RAG index produced no valid embeddings"})
        return {
            "success": False,
            "error": "RAG index produced no valid embeddings",
        }

    # Save to database with progress updates (80% -> 100%)
    rdir = rag_dir(output_dir)
    rdir.mkdir(parents=True, exist_ok=True)
    dp = rag_db_path(output_dir)

    # Run database write in executor and poll for progress
    total_rows = len(rows)
    rows_written = [0]  # Use list for mutable reference

    async def send_db_progress() -> None:
        """Send periodic progress updates during database write."""
        while rows_written[0] < total_rows:
            await asyncio.sleep(0.5)  # Update every 500ms
            if total_rows > 0:
                # Map 0-total_rows to 80-99%
                pct = rows_written[0] / total_rows
                progress = 80 + int(pct * 19)  # 80-99% range
                await manager.send_progress(job_id, progress, f"Writing to database: {rows_written[0]}/{total_rows} chunks...")
        # Final update
        await manager.send_progress(job_id, 99, f"Finalizing database write...")

    def run_db_write() -> None:
        """Run database write and update row counter."""
        conn = sqlite3.connect(str(dp))
        try:
            conn.execute("DROP TABLE IF EXISTS chunks")
            init_db(conn)
            for i, (kind, ref, body, vec) in enumerate(rows):
                if not vec:
                    continue
                dim = len(vec)
                conn.execute(
                    "INSERT INTO chunks (source_kind, source_ref, body, dim, vec) VALUES (?, ?, ?, ?, ?)",
                    (kind, ref, body, dim, struct.pack(f"{len(vec)}f", *vec)),
                )
                rows_written[0] = i + 1
            conn.commit()
        finally:
            conn.close()

    # Start progress updater and database write concurrently
    progress_task = asyncio.create_task(send_db_progress())

    try:
        await asyncio.get_event_loop().run_in_executor(None, run_db_write)
    finally:
        # Ensure progress task completes
        rows_written[0] = total_rows  # Signal completion
        try:
            await asyncio.wait_for(progress_task, timeout=2.0)
        except asyncio.TimeoutError:
            pass  # Task will exit on next iteration

    # Write manifest
    sources = compute_source_fingerprints(output_dir)
    mp = rag_manifest_path(output_dir)
    manifest_obj = {
        "rag_schema_version": RAG_SCHEMA_VERSION,
        "sources": sources,
        "embed_model": embed_model,
        "chunk_count": len(rows),
        "embed_dim": dim,
    }
    mp.write_text(json.dumps(manifest_obj, indent=2), encoding="utf-8")

    await manager.send_progress(job_id, 100, f"Index complete: {len(rows)} chunks")
    await manager.send_status(
        job_id,
        "completed",
        {
            "message": f"RAG index built successfully with {len(rows)} chunks",
            "chunk_count": len(rows),
            "embed_model": embed_model,
            "embed_dim": dim,
        },
    )

    log.info(
        "analytics_rag_build_complete",
        extra={
            "folder": output_dir.name,
            "job_id": job_id,
            "chunks": len(rows),
            "embed_dim": dim,
        },
    )

    return {
        "success": True,
        "chunk_count": len(rows),
        "embed_model": embed_model,
        "embed_dim": dim,
    }
