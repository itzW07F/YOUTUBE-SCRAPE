# ADR 0004: In-tree downloader and signature strategy

## Status

Proposed (initial scaffolding shipped; decipher engine pending)

## Context

Video bytes must not be obtained by shelling out to `yt-dlp` or similar tools, but many streams require deciphering player-specific transforms.

## Decision

- Implement download orchestration in-repo (`application/download_media.py`, `domain/format_selector.py`).
- Represent signature transforms behind a `SignatureTransformRunner` protocol.
- **Phase 1**: support **plain `url` formats** only; raise `UnsupportedFormatError` for `signatureCipher` / `cipher` until a vetted JS runner strategy is implemented and covered by vector tests.

## Consequences

- **Pros**: Clear extension point; tests can cover format selection without live YouTube.
- **Cons**: Full adaptive parity requires ongoing investment comparable to dedicated extractors.
