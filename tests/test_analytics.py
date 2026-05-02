"""Tests for deterministic analytics snapshot and Ollama report orchestration."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from youtube_scrape.adapters.ollama_client import (
    _extract_chat_content,
    _think_request_field,
    model_matches_installed,
)
from youtube_scrape.application.analytics_ollama_report import (
    build_comment_digest_for_llm,
    generate_ollama_macro_report,
    macro_brief_is_substantive,
    parse_macro_brief,
)
from youtube_scrape.application.analytics_snapshot import (
    build_analytics_snapshot,
    sort_metadata_history_chronologically,
)
from youtube_scrape.application.gallery_metadata_refresh import resolve_output_dir_for_refresh
from youtube_scrape.domain.analytics_aggregate import comment_corpus_fingerprint, flatten_comment_nodes
from youtube_scrape.domain.analytics_models import GuiAnalyticsLlmOverlay, MetadataHistoryPoint, OllamaMacroBrief
from youtube_scrape.settings import Settings

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "analytics"


@pytest.fixture
def analytics_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    sub = tmp_path / "abc123xyz01"
    sub.mkdir(parents=True)
    shutil.copy(FIXTURE_DIR / "video.json", sub / "video.json")
    shutil.copy(FIXTURE_DIR / "comments.json", sub / "comments.json")
    shutil.copy(FIXTURE_DIR / "metadata_history.jsonl", sub / "metadata_history.jsonl")
    resolved = resolve_output_dir_for_refresh(str(sub), [tmp_path.resolve()])
    assert resolved == sub.resolve()
    return sub.resolve()


def test_sort_metadata_history_chronologically_reorders_file() -> None:
    pts = [
        MetadataHistoryPoint(captured_at="2025-02-01T00:00:00Z", view_count=1000),
        MetadataHistoryPoint(captured_at="2025-01-01T00:00:00Z", view_count=900),
    ]
    got = sort_metadata_history_chronologically(pts)
    assert [p.view_count for p in got] == [900, 1000]


def test_build_analytics_snapshot_sorts_history_when_jsonl_newest_first(tmp_path: Path) -> None:
    """Lines reversed vs chronological fixture — snapshot must still plot oldest → newest."""
    sub = tmp_path / "revsub"
    sub.mkdir(parents=True)
    lines = [
        '{"schema_version": "1", "captured_at": "2025-02-01T00:00:00Z", "video_id": "v", "metrics": {"view_count": 1000}}',
        '{"schema_version": "1", "captured_at": "2025-01-01T00:00:00Z", "video_id": "v", "metrics": {"view_count": 900}}',
    ]
    (sub / "metadata_history.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (sub / "video.json").write_text(
        '{"data": {"metadata": {"video_id": "v", "view_count": 1000}}}', encoding="utf-8"
    )
    snap = build_analytics_snapshot(sub)
    assert [p.view_count for p in snap.metadata_history] == [900, 1000]


def test_backfills_comment_count_from_metadata_history_when_video_json_omits_it(
    tmp_path: Path,
) -> None:
    sub = tmp_path / "no_cc"
    sub.mkdir(parents=True)
    shutil.copy(FIXTURE_DIR / "video.json", sub / "video.json")
    inner = json.loads((sub / "video.json").read_text(encoding="utf-8"))
    del inner["data"]["metadata"]["comment_count"]
    (sub / "video.json").write_text(json.dumps(inner, indent=2), encoding="utf-8")
    shutil.copy(FIXTURE_DIR / "metadata_history.jsonl", sub / "metadata_history.jsonl")
    shutil.copy(FIXTURE_DIR / "comments.json", sub / "comments.json")

    snap = build_analytics_snapshot(sub)
    assert snap.video_metrics is not None
    assert snap.video_metrics.comment_count == 100
    assert any("comment total was missing from video.json" in n for n in snap.notes)


def test_resolve_output_dir_rejects_escape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    malicious = Path("/etc/passwd")
    with pytest.raises(ValueError):
        resolve_output_dir_for_refresh(str(malicious), [tmp_path.resolve()])


def test_build_analytics_snapshot(analytics_output: Path) -> None:
    snap = build_analytics_snapshot(analytics_output)
    assert snap.video_metrics is not None
    assert snap.video_metrics.video_id == "abc123xyz01"
    assert snap.video_metrics.view_count == 1000
    assert snap.video_metrics.comment_count == 100
    assert snap.video_metrics.description == "Fixture short description for analytics video."
    assert len(snap.metadata_history) == 2
    assert snap.metadata_history[0].view_count == 900
    assert snap.comment_stats is not None
    assert snap.comment_stats.total_flat == 3
    assert snap.comment_stats.reply_count == 1
    terms = {k.term for k in snap.keywords}
    assert "python" in terms or "tutorial" in terms


def test_build_analytics_snapshot_flat_comments_without_envelope(analytics_output: Path) -> None:
    """Legacy or hand-edited folders may store comments at the root (GUI reader already accepts this)."""

    flat = {
        "comments": [
            {
                "comment_id": "flat1",
                "text": "Root-level envelope test",
                "author": "Sam",
                "like_count": 3,
                "is_reply": False,
                "replies": [],
            }
        ]
    }
    (analytics_output / "comments.json").write_text(json.dumps(flat), encoding="utf-8")
    snap = build_analytics_snapshot(analytics_output)
    assert snap.comment_stats is not None
    assert snap.comment_stats.total_flat == 1


def test_flatten_and_fingerprint() -> None:
    raw = json.loads((FIXTURE_DIR / "comments.json").read_text(encoding="utf-8"))
    inner = raw["data"]["comments"]
    flat = flatten_comment_nodes(inner)
    assert len(flat) == 3
    fp1 = comment_corpus_fingerprint(flat)
    fp2 = comment_corpus_fingerprint(flat)
    assert fp1 == fp2


def test_parse_macro_brief_strips_fence() -> None:
    raw = """```json
{"themes":["a"],"sentiment_overview":"x","suggestions_and_requests":"","complaints_and_criticism":"","agreements_and_disagreements":"","notable_quotes":[],"caveats":[]}
```"""
    brief = parse_macro_brief(raw)
    assert brief.themes == ["a"]


def test_parse_macro_brief_extracts_json_from_prose() -> None:
    payload = {
        "themes": ["tidbit"],
        "sentiment_overview": "Mostly curious engagement with neutral undertones.",
        "suggestions_and_requests": "",
        "complaints_and_criticism": "",
        "agreements_and_disagreements": "",
        "notable_quotes": [],
        "caveats": [],
    }
    blob = json.dumps(payload)
    raw = f"Analysis follows:\n{blob}\n(end)"
    brief = parse_macro_brief(raw)
    assert brief.themes == ["tidbit"]


def test_macro_brief_is_substantive_empty_vs_filled() -> None:
    assert not macro_brief_is_substantive(OllamaMacroBrief())
    assert macro_brief_is_substantive(OllamaMacroBrief(themes=["one"]))
    assert macro_brief_is_substantive(OllamaMacroBrief(sentiment_overview="x" * 16))
    assert not macro_brief_is_substantive(OllamaMacroBrief(sentiment_overview="x" * 15))
    # Thin spread across several fields still counts as substantive.
    assert macro_brief_is_substantive(
        OllamaMacroBrief(
            sentiment_overview="123456789012",
            suggestions_and_requests="123456789012",
            complaints_and_criticism="123456789012",
            agreements_and_disagreements="123456789012",
        )
    )


def test_extract_chat_prefers_thinking_when_content_is_trivial_json() -> None:
    rich = json.dumps(
        {
            "themes": ["t"],
            "sentiment_overview": "Audience reactions vary but skew constructive.",
            "suggestions_and_requests": "",
            "complaints_and_criticism": "",
            "agreements_and_disagreements": "",
            "notable_quotes": [],
            "caveats": [],
        }
    )
    picked = _extract_chat_content({"message": {"content": "{}", "thinking": rich}})
    assert picked == rich


def test_extract_chat_coerces_content_from_multimodal_parts_list() -> None:
    rich = json.dumps(
        {
            "themes": ["part"],
            "sentiment_overview": "x" * 24,
            "suggestions_and_requests": "",
            "complaints_and_criticism": "",
            "agreements_and_disagreements": "",
            "notable_quotes": [],
            "caveats": [],
        }
    )
    picked = _extract_chat_content({"message": {"content": [{"type": "text", "text": rich}]}})
    assert picked == rich


def test_extract_chat_coerces_content_dict_with_text_shape() -> None:
    rich = json.dumps(
        {
            "themes": ["wrapped"],
            "sentiment_overview": "z" * 24,
            "suggestions_and_requests": "",
            "complaints_and_criticism": "",
            "agreements_and_disagreements": "",
            "notable_quotes": [],
            "caveats": [],
        }
    )
    picked = _extract_chat_content({"message": {"content": {"type": "text", "text": rich}}})
    assert picked == rich


def test_extract_chat_uses_reasoning_when_content_empty() -> None:
    rich = json.dumps(
        {
            "themes": ["r"],
            "sentiment_overview": "y" * 24,
            "suggestions_and_requests": "",
            "complaints_and_criticism": "",
            "agreements_and_disagreements": "",
            "notable_quotes": [],
            "caveats": [],
        }
    )
    picked = _extract_chat_content({"message": {"content": "", "reasoning": rich}})
    assert picked == rich


def test_digest_includes_breadth_not_only_high_like_tangent() -> None:
    """Highly liked tangent thread cannot be the only slice visible to the LLM."""

    flat: list[dict[str, object]] = []
    for i in range(40):
        flat.append(
            {
                "comment_id": f"p{i:04d}",
                "text": f"Episode debate on politics and world events thread {i}",
                "author": f"viewer{i}",
                "like_count": 2,
            }
        )
    for j in range(10):
        flat.append(
            {
                "comment_id": f"g{j}",
                "text": "Unrelated gaming graphics camera angles tangent",
                "author": "one_off_topic",
                "like_count": 900 + j,
            }
        )

    digest, meta = build_comment_digest_for_llm(flat, None)
    assert meta["digest_spread_rows_added"] > 0
    assert "politics and world events" in digest
    assert meta["digest_unique_comments"] == 50


def test_model_matches_installed_tag_variants() -> None:
    installed = ["llama3:latest", "mistral:7b"]
    assert model_matches_installed("llama3", installed)
    assert model_matches_installed("llama3:latest", installed)
    assert model_matches_installed("Llama3:latest", installed)
    assert model_matches_installed("mistral", installed)
    assert not model_matches_installed("llama3.2", installed)


def test_think_request_field_gpt_oss_uses_string_level() -> None:
    assert _think_request_field("gpt-oss:20b") == "low"
    assert _think_request_field("My-GPT-OSS-test") == "low"
    assert _think_request_field("llama3.2") is True


@pytest.mark.asyncio
async def test_generate_ollama_macro_report_uses_mock(analytics_output: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTPUT_DIR", str(analytics_output.parent))

    fake_json = json.dumps(
        {
            "themes": ["testing"],
            "sentiment_overview": "neutral",
            "suggestions_and_requests": "",
            "complaints_and_criticism": "",
            "agreements_and_disagreements": "",
            "notable_quotes": [],
            "caveats": ["fixture"],
        }
    )

    class _FakeLlm:
        async def ensure_ready(self, *, timeout_s: float) -> None:
            return

        async def chat(
            self,
            *,
            system: str | None,
            user: str,
            json_format: bool,
            timeout_s: float,
            log_context: str,
        ) -> str:
            _ = (system, json_format, timeout_s, log_context)
            return fake_json

    def _fake_build(settings: Settings) -> _FakeLlm:
        _ = settings
        return _FakeLlm()

    with patch(
        "youtube_scrape.application.analytics_ollama_report.build_analytics_llm",
        side_effect=_fake_build,
    ):
        settings = Settings()
        report = await generate_ollama_macro_report(analytics_output, settings=settings, force_refresh=True)

    assert report.brief.themes == ["testing"]
    assert report.from_cache is False

    cache_path = analytics_output / "analytics_llm_cache.json"
    assert cache_path.is_file()


@pytest.mark.asyncio
async def test_probe_analytics_llm_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUTUBE_SCRAPE_ANALYTICS_OLLAMA_ENABLED", "false")
    from youtube_scrape.adapters.llm_providers import probe_analytics_llm

    out = await probe_analytics_llm(Settings())
    assert out["ok"] is False
    assert out["provider"] == "ollama"


@pytest.mark.asyncio
async def test_probe_analytics_llm_ollama_ok() -> None:
    from youtube_scrape.adapters.llm_providers import probe_analytics_llm

    with patch(
        "youtube_scrape.adapters.llm_providers.ollama_list_model_names",
        new_callable=AsyncMock,
        return_value=["llama3:latest"],
    ):
        out = await probe_analytics_llm(Settings())
    assert out["ok"] is True
    assert out["provider"] == "ollama"


@pytest.mark.asyncio
async def test_probe_analytics_llm_openai_compatible_patched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUTUBE_SCRAPE_ANALYTICS_LLM_PROVIDER", "openai_compatible")
    monkeypatch.delenv("YOUTUBE_SCRAPE_OPENAI_COMPATIBLE_API_KEY", raising=False)

    from youtube_scrape.adapters.llm_providers import OpenAiCompatibleBackend, probe_analytics_llm

    with patch.object(
        OpenAiCompatibleBackend,
        "probe",
        new_callable=AsyncMock,
        return_value=(True, "Reachable via GET /v1/models.", ["gpt-4o-mini"]),
    ):
        out = await probe_analytics_llm(Settings())
    assert out["ok"] is True
    assert out["models_sample"] == ["gpt-4o-mini"]


def test_normalize_ollama_base_url_adds_scheme() -> None:
    from youtube_scrape.adapters.ollama_client import normalize_ollama_base_url

    assert normalize_ollama_base_url("192.168.1.203:11434") == "http://192.168.1.203:11434"
    assert normalize_ollama_base_url("  http://local:11434/  ") == "http://local:11434"
    assert normalize_ollama_base_url("https://ollama.example") == "https://ollama.example"


def test_settings_ollama_base_url_env_without_scheme_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUTUBE_SCRAPE_OLLAMA_BASE_URL", "10.0.0.5:11434")
    got = Settings()
    assert got.ollama_base_url == "http://10.0.0.5:11434"


def test_effective_analytics_llm_gui_overlay_prefers_remote_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """Electron sends gui_llm_overlay on each Analytics call so remote Ollama overrides stale server env."""

    monkeypatch.setenv("YOUTUBE_SCRAPE_OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    from youtube_scrape.application.analytics_gui_llm_resolve import effective_analytics_llm_settings

    merged = effective_analytics_llm_settings(
        gui=GuiAnalyticsLlmOverlay(ollama_base_url="http://192.168.1.203:11434"),
    )
    assert merged.ollama_base_url == "http://192.168.1.203:11434"


def test_effective_analytics_llm_gui_overlay_schemeless_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUTUBE_SCRAPE_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    from youtube_scrape.application.analytics_gui_llm_resolve import effective_analytics_llm_settings

    merged = effective_analytics_llm_settings(gui=GuiAnalyticsLlmOverlay(ollama_base_url="192.168.99.2:11434"))
    assert merged.ollama_base_url == "http://192.168.99.2:11434"
