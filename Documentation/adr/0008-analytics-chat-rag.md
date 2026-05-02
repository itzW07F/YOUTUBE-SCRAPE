# ADR 0008: Lightweight RAG for Analytics chat (“Ask the AI”)

## Status

Accepted

## Context

Analytics chat (`POST /analytics/chat`) injects a single concatenated scrape bundle capped at ~180 k characters. Large transcripts and comment corpora hit the budget quickly; relevance is fixed by section order, not the user’s question.

## Decision

1. **Optional retrieval (RAG)** behind `YOUTUBE_SCRAPE_ANALYTICS_RAG_ENABLED` / Settings, default **off** so existing deployments are unchanged.

2. **Embeddings** use **Ollama** `POST /api/embeddings` only. Non-Ollama chat providers do **not** use RAG yet (no extra cloud embedding dependency). Chat can still use OpenAI/Gemini while RAG stays disabled; when the provider is Ollama and RAG is on, embeddings use `YOUTUBE_SCRAPE_OLLAMA_EMBED_MODEL` (default `nomic-embed-text`).

3. **Storage** is a per-output-folder directory `.analytics_rag/` with:
   - `manifest.json` — RAG schema version, per-file SHA-256 of tracked artifacts, embed model id, vector dimension, chunk count.
   - `chunks.sqlite3` — chunk text plus float vectors (stdlib `sqlite3`, **no** extra vector DB package).

4. **Invalidation** when manifest sources, embed model, or RAG schema version disagree with disk → full index rebuild.

5. **Runtime behavior** builds a **hybrid** priming payload: compact **metadata header** + **top-k** retrieved chunks (labeled by source). On embedding failure, empty corpus, or any unexpected error → **fallback** to the existing `build_scrape_context_pack` full bundle (with warnings).

6. **GUI/Electron** may mirror toggles via store + spawn env; each chat request still merges `gui_llm_overlay` so behavior matches Settings without API restart.

## Consequences

- Users who enable RAG must run an Ollama **embedding** model (`ollama pull nomic-embed-text` or equivalent).
- First query after a scrape change may pay index-build + embed latency; subsequent queries reuse the SQLite index until sources change.
- Answers remain assistive; prompts require grounding in retrieved excerpts + header only.
