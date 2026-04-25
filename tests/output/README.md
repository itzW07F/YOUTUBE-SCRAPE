# Test output (review artifacts)

This directory holds **generated files** from opt-in integration tests so you can inspect JSON, thumbnails, and related outputs without digging through `/tmp`.

## Do not commit blobs

Generated files under `tests/output/reference/` are **gitignored**. Only this `README.md` and `.gitkeep` are tracked.

## How to generate artifacts

Requires Camoufox (`python -m camoufox fetch`) and network access.

```bash
export RUN_BROWSER_TESTS=1
export RUN_LIVE_REFERENCE_TESTS=1
# Optional: override default reference URL
# export REFERENCE_VIDEO_URL="https://www.youtube.com/watch?v=dYag3jVVfsQ"
# Headless often fails media capture; omit RUN_LIVE_REFERENCE_HEADFUL or use a real display.
# Default pytest.ini excludes live tests; override addopts for this module:
pytest --override-ini='addopts=' tests/test_live_reference_video.py -v
```

## Layout

After a successful run you should see:

- `tests/output/reference/<video_id>/video.json` — metadata envelope
- `tests/output/reference/<video_id>/thumbs.json` + `thumbs/` — downloaded poster variants
- `tests/output/reference/<video_id>/comments.json` — sample comments (live test asserts at least one; Innertube ``/next`` entity mutations are parsed)
- `tests/output/reference/<video_id>/transcript.txt` or `transcript.skip.txt` — captions or skip reason. Camoufox transcript scraping listens for in-page `/api/timedtext` responses so captions that require a **PO token** (`pot` query param) match what the web player actually loads.
- `tests/output/reference/<video_id>/download.json` + **`<sanitized video title>.mp4`** — full progressive stream when GVS accepts the URL (same strategies as the CLI ``download`` command), or `download.skip.txt` when the URL is **cipher-only**, **403 / PO-token blocked**, or transport fails (ADR-0004). On success, **`VIDEO_OUTPUT.txt`** contains the exact filename (useful when the title has punctuation).

CLI **full-file** download: ``--experimental-download``, ``--name-from-title -o <dir>`` (writes ``VIDEO_OUTPUT.txt`` in that dir), and **headed** Camoufox when possible; the live test uses ``selection=best`` and longer timeouts than metadata-only tests.
