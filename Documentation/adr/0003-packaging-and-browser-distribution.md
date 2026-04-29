# ADR 0003: Packaging and Camoufox distribution

## Status

Accepted

## Context

Releases must target Linux, macOS, and Windows while remaining honest about browser payload size.

## Decision

- Ship the Python application via **PyInstaller** one-folder bundles per OS in CI.
- Treat **Camoufox** as a **separate artifact**: either bundled next to the app in release zips or fetched with `python -m camoufox fetch` during install/bootstrap (documented in README).

## Consequences

- **Pros**: Clear separation between app runtime and browser binaries; smaller iteration loops on app-only changes.
- **Cons**: End users may need two download steps unless release engineering bundles both.
