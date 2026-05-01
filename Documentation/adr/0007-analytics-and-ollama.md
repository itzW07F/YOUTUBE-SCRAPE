# ADR 0007: Analytics module and optional Ollama synthesis

## Status

Accepted

## Context

The Electron GUI already persists scrape artifacts (`video.json`, `comments.json`, optional `metadata_history.jsonl` from gallery metadata refresh). Users want a dedicated Analytics surface for engagement metrics, historical trends, deterministic comment aggregates, and optional local LLM-assisted macro interpretation without sending data to third parties.

## Decision

1. **Deterministic analytics** live in the Python package under `youtube_scrape.domain` (pure aggregation) and `youtube_scrape.application.analytics_snapshot`, reading only files inside scrape output folders validated the same way as metadata refresh (`resolve_output_dir_for_refresh` + configured output roots).

2. **HTTP API** exposes `POST /analytics/snapshot` and `POST /analytics/ollama-report` (FastAPI router `api.routes.analytics`), keeping the Electron renderer thin (fetch only).

3. **Optional Ollama** is invoked via `httpx` to `YOUTUBE_SCRAPE_OLLAMA_BASE_URL` (default `http://127.0.0.1:11434`) using existing dependency policy — no new runtime libraries. Responses must validate against `OllamaMacroBrief`; one repair round is allowed on parse failure.

4. **On-disk cache** for LLM output: `analytics_llm_cache.json` beside artifacts, keyed by SHA-256 of sorted comment id + text, model id, and brief schema version.

5. **Trend charts** for views/likes/dislikes/public comment totals depend on **multiple** rows in `metadata_history.jsonl`; a single scrape produces only the current `video.json` point unless the gallery refresh pipeline has run more than once.

## Consequences

- Accurate “over time” charts require operational habit (periodic metadata refresh), which the Analytics UI surfaces explicitly.
- LLM output is **assistive**, not ground truth; prompts forbid individual profiling and the GUI repeats that limitation.
- Disabling remote-style analytics is possible with `YOUTUBE_SCRAPE_ANALYTICS_OLLAMA_ENABLED=false`.
- Tests mock Ollama HTTP (`ollama_chat_message`) so CI stays deterministic without a local model.
