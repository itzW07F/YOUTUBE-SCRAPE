# ADR 0002: No YouTube Data API; Camoufox + Playwright

## Status

Accepted

## Context

The product requires scraping fields that are not reliably available via official APIs and must resemble normal web clients to reduce bot friction.

## Decision

- Do **not** call YouTube Data API v3.
- Use **Camoufox** (stealth-oriented Firefox) with **Playwright** to load pages and reuse embedded JSON plus Innertube continuations.

## Consequences

- **Pros**: No API key management; richer page-aligned payloads.
- **Cons**: Higher maintenance when markup or embedded JSON shifts; heavier runtime (full browser).
