"""LLM-backed macro comment brief with on-disk cache (provider from Settings)."""

from __future__ import annotations

import json
import logging
import re
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from youtube_scrape.adapters.analytics_artifacts import envelope_inner_data, read_json_file
from youtube_scrape.adapters.llm_errors import LlmTransportError
from youtube_scrape.adapters.llm_providers import build_analytics_llm

from youtube_scrape.application.analytics_snapshot import video_metrics_from_metadata
from youtube_scrape.domain.analytics_aggregate import comment_corpus_fingerprint, flatten_comment_nodes
from youtube_scrape.domain.analytics_models import (
    AnalyticsLlmCacheFile,
    OllamaMacroBrief,
    OllamaReportPayload,
    VideoMetricsSummary,
)
from youtube_scrape.settings import Settings

log = logging.getLogger(__name__)

_CACHE_NAME = "analytics_llm_cache.json"
_BRIEF_SCHEMA_VERSION = "5"
_MAX_DIGEST_CHARS = 52_000
_MAX_DIGEST_ROWS_SOFT = 420
_MAX_DIGEST_LINES_PER_AUTHOR = 6
_DIGEST_SPREAD_RESERVE_ROWS = 72


def _strip_json_fence(raw: str) -> str:
    s = raw.strip()
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", s)
    if fence:
        return fence.group(1).strip()
    return s


def _extract_outer_json_object(s: str) -> str | None:
    """First balanced ``{...}`` slice; handles prose before/after JSON."""

    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(s)):
        ch = s[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def macro_brief_is_substantive(brief: OllamaMacroBrief) -> bool:
    """False when the model returned syntactically valid but useless empty fields."""

    blobs = (
        brief.sentiment_overview,
        brief.suggestions_and_requests,
        brief.complaints_and_criticism,
        brief.agreements_and_disagreements,
    )
    blob_total_non_ws = sum(len(x.strip()) for x in blobs)
    # Single-field gate was 24 chars and rejected many legitimate short summaries from smaller models.
    min_blob = 16
    min_blob_sum = 48
    return (
        any(t.strip() for t in brief.themes)
        or any(len(x.strip()) >= min_blob for x in blobs)
        or blob_total_non_ws >= min_blob_sum
        or any(q.strip() for q in brief.notable_quotes)
        or any(c.strip() for c in brief.caveats)
    )


def parse_macro_brief(raw: str) -> OllamaMacroBrief:
    cleaned = _strip_json_fence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        blob = _extract_outer_json_object(cleaned)
        if blob is None:
            raise
        data = json.loads(blob)
    if not isinstance(data, dict):
        raise ValueError("brief JSON root must be an object")
    return OllamaMacroBrief.model_validate(data)


def _load_flat_comments(output_dir: Path) -> list[dict[str, Any]]:
    cenv = read_json_file(output_dir / "comments.json")
    if cenv is None:
        return []
    data = envelope_inner_data(cenv)
    raw_comments = data.get("comments")
    if not isinstance(raw_comments, list):
        return []
    return flatten_comment_nodes(raw_comments)


def _load_video_metrics(output_dir: Path) -> VideoMetricsSummary | None:
    env = read_json_file(output_dir / "video.json")
    if env is None:
        return None
    inner = envelope_inner_data(env)
    meta = inner.get("metadata")
    return video_metrics_from_metadata(meta) if isinstance(meta, dict) else None


def _like_int(row: dict[str, Any]) -> int:
    lc = row.get("like_count")
    if isinstance(lc, bool):
        return 0
    if isinstance(lc, int | float) and lc >= 0:
        return int(lc)
    return 0


def _comment_id_stable(row: dict[str, Any], fallback_index: int) -> str:
    cid = str(row.get("comment_id") or "").strip()
    return cid if cid else f"__row_{fallback_index}"


def _unique_comment_rows(flat: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Deduplicate by comment id; keep highest-like duplicate."""

    best: dict[str, tuple[str, dict[str, Any]]] = {}
    for i, r in enumerate(flat):
        cid = _comment_id_stable(r, i)
        prev = best.get(cid)
        if prev is None or _like_int(r) > _like_int(prev[1]):
            best[cid] = (cid, r)
    return sorted(best.values(), key=lambda t: t[0])


def _author_bucket(row: dict[str, Any]) -> str:
    a = str(row.get("author") or "").strip()
    return a if a else "(unknown)"


def _select_digest_rows(flat: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Mix high-engagement comments with an ID-spread sample so one tangent cannot dominate."""

    unique_pairs = _unique_comment_rows(flat)
    if not unique_pairs:
        return [], {
            "digest_unique_comments": 0,
            "digest_high_engagement_rows": 0,
            "digest_spread_rows_added": 0,
            "digest_max_lines_per_author": _MAX_DIGEST_LINES_PER_AUTHOR,
        }

    n_unique = len(unique_pairs)
    seen_ids: set[str] = set()
    ordered: list[dict[str, Any]] = []
    per_author: dict[str, int] = {}

    high_budget = max(40, _MAX_DIGEST_ROWS_SOFT - _DIGEST_SPREAD_RESERVE_ROWS)
    eng_cap = min(high_budget, max(24, n_unique // 2))

    def can_take_author(author: str) -> bool:
        return per_author.get(author, 0) < _MAX_DIGEST_LINES_PER_AUTHOR

    def push(cid: str, row: dict[str, Any]) -> None:
        if cid in seen_ids:
            return
        auth = _author_bucket(row)
        if not can_take_author(auth):
            return
        ordered.append(row)
        seen_ids.add(cid)
        per_author[auth] = per_author.get(auth, 0) + 1

    # Pass 1: engagement-weighted order with per-author cap (leave room for breadth pass)
    by_likes = sorted(unique_pairs, key=lambda t: _like_int(t[1]), reverse=True)
    for cid, row in by_likes:
        push(cid, row)
        if len(ordered) >= eng_cap:
            break

    high_engagement_rows = len(ordered)

    # Pass 2: breadth — evenly spaced across stable comment-id ordering
    spread_target = min(120, max(24, n_unique // 3))
    if n_unique > 0 and spread_target > 0:
        for j in range(spread_target):
            idx = int(j * (n_unique - 1) / max(1, spread_target - 1)) if spread_target > 1 else 0
            cid, row = unique_pairs[idx]
            push(cid, row)
            if len(ordered) >= _MAX_DIGEST_ROWS_SOFT:
                break

    spread_added = len(ordered) - high_engagement_rows
    meta = {
        "digest_unique_comments": n_unique,
        "digest_high_engagement_rows": high_engagement_rows,
        "digest_spread_rows_added": max(0, spread_added),
        "digest_engagement_cap": eng_cap,
        "digest_max_lines_per_author": _MAX_DIGEST_LINES_PER_AUTHOR,
    }
    return ordered, meta


def build_comment_digest_for_llm(
    flat: list[dict[str, Any]],
    metrics: VideoMetricsSummary | None,
    *,
    max_chars: int = _MAX_DIGEST_CHARS,
) -> tuple[str, dict[str, Any]]:
    """Build text digest for the LLM; stratified rows plus char budget."""

    rows, digest_strategy_meta = _select_digest_rows(flat)
    header_parts: list[str] = []
    if metrics:
        header_parts.append(
            "Video context: "
            + ", ".join(
                f"{k}={v}"
                for k, v in {
                    "title": metrics.title,
                    "channel": metrics.channel_title,
                    "views": metrics.view_count,
                    "likes": metrics.like_count,
                    "comments_public_total": metrics.comment_count,
                }.items()
                if v is not None
            )
        )
    header = "\n".join(header_parts)
    body_parts: list[str] = []
    used = len(header) + 24
    included = 0
    for r in rows:
        cid = str(r.get("comment_id") or "").strip() or "?"
        auth = str(r.get("author") or "unknown")
        txt = str(r.get("text") or "").replace("\r\n", "\n").strip()
        likes = r.get("like_count")
        line = f"[{cid}] ({likes if likes is not None else '?'}) {auth}: {txt}\n"
        if used + len(line) > max_chars:
            break
        body_parts.append(line)
        used += len(line)
        included += 1

    digest = (header + "\n\nComments:\n" + "".join(body_parts)).strip()
    meta = {
        "total_comments": len(flat),
        "included_comments": included,
        "truncated": included < len(rows),
        **digest_strategy_meta,
    }
    return digest, meta


def _prompt_main(digest: str) -> str:
    schema_hint = (
        '{"themes":["string"],"sentiment_overview":"string",'
        '"suggestions_and_requests":"string","complaints_and_criticism":"string",'
        '"agreements_and_disagreements":"string","notable_quotes":["string"],"caveats":["string"]}'
    )
    return (
        "You summarize how viewers reacted to ONE YouTube video or podcast episode, using ONLY the "
        "evidence in the digest below.\n\n"
        "INPUT: Optional \"Video context:\" (title/channel/metrics) plus a \"Comments:\" section. "
        'Each line is one real comment: [comment_id] (likes) author: text.\n\n'
        "YOUR JOB:\n"
        "- Infer dominant topics commenters discuss **in relation to this video/channel** and how they "
        "emotionally frame them (support, outrage, sarcasm, curiosity, etc.). These are language cues only — "
        "not clinical diagnoses and not profiling named people.\n"
        "- Capture disagreements, factions, or recurring asks directed at the creator.\n\n"
        "GROUNDING RULES (critical):\n"
        "- Every theme must be justified by **recurring wording or ideas in the Comments lines**. "
        "Do not invent subjects (unrelated industries, games, hobbies, etc.) unless comment text clearly "
        "supports them.\n"
        "- If highly liked comments focus on a side tangent but many other lines discuss the main episode "
        "topic, reflect **both** proportionally; note imbalance in \"caveats\".\n"
        '- notable_quotes: short excerpts **taken from** comment lines below (trim wording lightly at most).\n'
        "- Do NOT fabricate quotes or attribute motives to individuals.\n\n"
        "Output ONLY valid JSON (no markdown fences, no commentary outside JSON) with exactly these keys: "
        "themes (array of short strings), sentiment_overview (string), suggestions_and_requests (string), "
        "complaints_and_criticism (string), agreements_and_disagreements (string), notable_quotes (array "
        "of strings), caveats (array of strings).\n"
        "Example shape: "
        + schema_hint
        + "\n\n--- COMMENT DIGEST (sole evidence for themes and sentiment) ---\n"
        + digest
    )


def _prompt_plain_json_fallback(digest: str) -> str:
    """Last resort without Ollama ``format: json`` — helps reasoning/thinking tags that emit ``{}`` in content."""

    excerpt = digest.strip()
    if len(excerpt) > 26_000:
        excerpt = excerpt[:26_000] + "\n… [digest truncated]"
    schema_hint = (
        '{"themes":["short topic","…"],"sentiment_overview":"one+ sentences",'
        '"suggestions_and_requests":"…","complaints_and_criticism":"…","agreements_and_disagreements":"…",'
        '"notable_quotes":["…"],"caveats":["…"]}'
    )
    return (
        "TASK: Summarize viewer reactions using ONLY the digest below.\n"
        "Reply with ONE JSON object and NOTHING else (no markdown fences, no preamble).\n"
        "Keys exactly: themes (array, min 4 strings), sentiment_overview, suggestions_and_requests, "
        "complaints_and_criticism, agreements_and_disagreements, notable_quotes, caveats.\n"
        "Every string field must have real sentences grounded in the comments; themes must be substantive phrases.\n"
        "Example shape: "
        + schema_hint
        + "\n\n--- DIGEST ---\n"
        + excerpt
    )


def _prompt_repair(bad_snippet: str) -> str:
    return (
        "The following text was supposed to be JSON for keys "
        "themes, sentiment_overview, suggestions_and_requests, complaints_and_criticism, "
        "agreements_and_disagreements, notable_quotes, caveats. "
        "Reply with ONLY corrected valid JSON.\n\n"
        + bad_snippet[:8000]
    )


def _prompt_refill_empty(previous_raw: str, digest_excerpt: str) -> str:
    excerpt = digest_excerpt.strip()
    if len(excerpt) > 14_000:
        excerpt = excerpt[:14_000] + "\n… [digest truncated for refill context]"
    return (
        "Your previous reply was valid JSON but every meaningful field was empty "
        "(no themes, no sentences in text fields).\n"
        "Reply with ONLY one JSON object using exactly these keys: "
        "themes (array of at least 4 short strings), sentiment_overview, "
        "suggestions_and_requests, complaints_and_criticism, agreements_and_disagreements, "
        "notable_quotes (array), caveats (array).\n"
        "Ground EVERYTHING in the COMMENT DIGEST excerpt below (same rules as the main prompt: no invented "
        "topics; quotes must match comment wording).\n\n"
        "--- COMMENT DIGEST (evidence) ---\n"
        + excerpt
        + "\n\n--- Previous weak JSON to discard ---\n"
        + previous_raw[:12000]
    )


def _read_cache(cache_path: Path) -> AnalyticsLlmCacheFile | None:
    raw = read_json_file(cache_path)
    if raw is None:
        return None
    try:
        return AnalyticsLlmCacheFile.model_validate(raw)
    except ValidationError:
        return None


def _write_cache(cache_path: Path, payload: AnalyticsLlmCacheFile) -> None:
    cache_path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")


async def generate_ollama_macro_report(
    output_dir: Path,
    *,
    settings: Settings | None = None,
    force_refresh: bool = False,
) -> OllamaReportPayload:
    """Load comments, use cache when possible, call Ollama, persist cache."""

    settings = settings or Settings()

    folder_tag = output_dir.name
    log.info(
        "analytics_ollama_report_start",
        extra={
            "folder": folder_tag,
            "force_refresh": force_refresh,
            "llm_provider": settings.analytics_llm_provider,
            "model": settings.analytics_llm_model_label(),
            "timeout_s": settings.ollama_timeout_s,
        },
    )

    if not settings.analytics_ollama_enabled:
        raise LlmTransportError("LLM analytics disabled via settings (analytics_ollama_enabled=false).")

    flat = _load_flat_comments(output_dir)
    if not flat:
        raise ValueError("No comments loaded — include comments.json in this scrape folder.")

    fingerprint = comment_corpus_fingerprint(flat)
    cache_path = output_dir / _CACHE_NAME
    model = settings.analytics_llm_model_label()
    llm = build_analytics_llm(settings)

    if not force_refresh:
        cached = _read_cache(cache_path)
        if (
            cached is not None
            and cached.comment_set_sha256 == fingerprint
            and cached.model == model
            and cached.brief_schema_version == _BRIEF_SCHEMA_VERSION
        ):
            substantive = macro_brief_is_substantive(cached.brief)
            log.info(
                "analytics_ollama_report_cache_hit",
                extra={
                    "folder": folder_tag,
                    "model": model,
                    "cache_schema": cached.brief_schema_version,
                    "brief_substantive": substantive,
                },
            )
            if not substantive:
                log.warning(
                    "analytics_ollama_report_cache_hit_but_empty_brief",
                    extra={
                        "folder": folder_tag,
                        "hint": "Use Force refresh to regenerate after upgrading the app.",
                    },
                )
            gen_at = cached.generated_at
            return OllamaReportPayload(
                output_dir=str(output_dir),
                model=model,
                generated_at=gen_at,
                from_cache=True,
                comment_digest_meta={"total_comments": len(flat), "from_cache": True},
                brief=cached.brief,
            )

    metrics = _load_video_metrics(output_dir)
    digest, digest_meta = build_comment_digest_for_llm(flat, metrics)
    log.info(
        "analytics_ollama_digest_built",
        extra={
            "folder": folder_tag,
            "fingerprint_prefix": fingerprint[:12],
            "flat_comments": len(flat),
            **digest_meta,
            "digest_chars": len(digest),
        },
    )

    probe_timeout = min(15.0, float(settings.ollama_timeout_s))
    await llm.ensure_ready(timeout_s=probe_timeout)

    prompt = _prompt_main(digest)
    raw = await llm.chat(
        system=None,
        user=prompt,
        json_format=True,
        timeout_s=settings.ollama_timeout_s,
        log_context="analytics_llm_main",
    )
    log.info(
        "analytics_llm_first_reply",
        extra={"folder": folder_tag, "raw_chars": len(raw), "raw_head": raw[:200].replace("\n", "\\n")},
    )

    brief: OllamaMacroBrief
    try:
        brief = parse_macro_brief(raw)
    except (json.JSONDecodeError, ValueError, ValidationError) as exc:
        log.warning(
            "analytics_llm_parse_failed_attempt_repair",
            extra={
                "folder": folder_tag,
                "exc_type": type(exc).__name__,
                "detail": str(exc)[:400],
            },
        )
        repair = await llm.chat(
            system=None,
            user=_prompt_repair(raw),
            json_format=True,
            timeout_s=min(settings.ollama_timeout_s, 120.0),
            log_context="analytics_llm_repair",
        )
        log.info(
            "analytics_llm_repair_reply",
            extra={"folder": folder_tag, "raw_chars": len(repair)},
        )
        try:
            brief = parse_macro_brief(repair)
        except (json.JSONDecodeError, ValueError, ValidationError) as exc2:
            log.error(
                "analytics_llm_parse_failed_after_repair",
                extra={"folder": folder_tag, "detail": str(exc2)[:500]},
            )
            raise LlmTransportError("Could not parse LLM JSON brief after repair") from exc2

    substantive = macro_brief_is_substantive(brief)
    log.info(
        "analytics_llm_brief_parsed",
        extra={
            "folder": folder_tag,
            "substantive": substantive,
            "theme_count": len(brief.themes),
            "sentiment_chars": len(brief.sentiment_overview.strip()),
        },
    )

    if not substantive:
        log.warning(
            "analytics_llm_brief_empty_running_refill",
            extra={"folder": folder_tag},
        )
        refill = await llm.chat(
            system=None,
            user=_prompt_refill_empty(raw, digest),
            json_format=True,
            timeout_s=min(settings.ollama_timeout_s, 180.0),
            log_context="analytics_llm_refill",
        )
        log.info(
            "analytics_llm_refill_reply",
            extra={"folder": folder_tag, "raw_chars": len(refill)},
        )
        try:
            brief = parse_macro_brief(refill)
        except (json.JSONDecodeError, ValueError, ValidationError) as exc:
            log.error(
                "analytics_llm_refill_parse_failed",
                extra={"folder": folder_tag, "detail": str(exc)[:500]},
            )
            raise LlmTransportError(
                "Could not parse LLM JSON brief after empty-fields refill pass"
            ) from exc
        substantive = macro_brief_is_substantive(brief)
        log.info(
            "analytics_llm_after_refill",
            extra={
                "folder": folder_tag,
                "substantive": substantive,
                "theme_count": len(brief.themes),
            },
        )
        if not substantive:
            log.warning(
                "analytics_llm_still_empty_after_refill_try_plain_fallback",
                extra={"folder": folder_tag},
            )
            plain_prompt = _prompt_plain_json_fallback(digest)
            plain_raw = await llm.chat(
                system=None,
                user=plain_prompt,
                json_format=False,
                timeout_s=min(settings.ollama_timeout_s, 240.0),
                log_context="analytics_llm_plain_fallback",
            )
            log.info(
                "analytics_llm_plain_fallback_reply",
                extra={"folder": folder_tag, "raw_chars": len(plain_raw)},
            )
            try:
                brief = parse_macro_brief(plain_raw)
            except (json.JSONDecodeError, ValueError, ValidationError) as exc:
                log.warning(
                    "analytics_llm_plain_fallback_parse_failed_attempt_repair",
                    extra={
                        "folder": folder_tag,
                        "exc_type": type(exc).__name__,
                        "detail": str(exc)[:400],
                    },
                )
                repair_plain = await llm.chat(
                    system=None,
                    user=_prompt_repair(plain_raw),
                    json_format=True,
                    timeout_s=min(settings.ollama_timeout_s, 120.0),
                    log_context="analytics_llm_plain_fallback_repair",
                )
                try:
                    brief = parse_macro_brief(repair_plain)
                except (json.JSONDecodeError, ValueError, ValidationError) as exc2:
                    log.error(
                        "analytics_llm_plain_fallback_repair_failed",
                        extra={"folder": folder_tag, "detail": str(exc2)[:500]},
                    )
                    raise LlmTransportError(
                        "Could not parse analytics brief after plain-json fallback and repair."
                    ) from exc2

            substantive = macro_brief_is_substantive(brief)
            log.info(
                "analytics_llm_after_plain_fallback",
                extra={
                    "folder": folder_tag,
                    "substantive": substantive,
                    "theme_count": len(brief.themes),
                },
            )
            if not substantive:
                log.error(
                    "analytics_llm_substantive_failed_after_plain_fallback",
                    extra={"folder": folder_tag},
                )
                raise LlmTransportError(
                    "The model never produced a substantive analytics brief (structured JSON, refill, "
                    "and plain-json fallback all yielded empty or token replies). Reasoning/thinking "
                    "models often hide JSON outside assistant text for some APIs. Try a plain instruct model, "
                    "adjust analytics_llm_provider / model env, or upgrade/pull weights."
                )

    gen_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    cache_payload = AnalyticsLlmCacheFile(
        comment_set_sha256=fingerprint,
        model=model,
        brief_schema_version=_BRIEF_SCHEMA_VERSION,
        generated_at=gen_at,
        brief=brief,
    )
    with suppress(OSError):
        _write_cache(cache_path, cache_payload)

    log.info(
        "analytics_ollama_report_done",
        extra={
            "folder": folder_tag,
            "from_cache": False,
            "wrote_cache": cache_path.name,
            "theme_count": len(brief.themes),
        },
    )

    merged_meta = {**digest_meta, "total_comments": len(flat)}
    return OllamaReportPayload(
        output_dir=str(output_dir),
        model=model,
        generated_at=gen_at,
        from_cache=False,
        comment_digest_meta=merged_meta,
        brief=brief,
    )
