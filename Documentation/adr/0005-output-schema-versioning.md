# ADR 0005: Output schema versioning

## Status

Accepted

## Context

Downstream tooling (future Electron UI) needs stable JSON while the scraper evolves.

## Decision

- Wrap CLI JSON outputs in `ResultEnvelope` with `schema_version` sourced from `Settings.output_schema_version`.

## Consequences

Consumers can branch on `schema_version` while the internal domain models change.
