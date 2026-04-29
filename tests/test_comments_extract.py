import json
from datetime import UTC, datetime
from pathlib import Path

from youtube_scrape.domain.comments_extract import (
    extract_comment_records_from_response,
    extract_comments_from_entity_mutations,
    extract_comments_from_initial_data,
    extract_continuation_tokens,
    response_has_comment_entities,
)


def test_extract_comments_thread() -> None:
    now_utc = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    data = json.loads(
        (Path(__file__).parent / "fixtures" / "initial_data_comments_min.json").read_text(encoding="utf-8")
    )
    comments = extract_comments_from_initial_data(data, now_utc=now_utc)
    assert len(comments) == 2
    assert comments[0].comment_id == "abc"
    assert comments[0].is_reply is False
    assert comments[0].published_at == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert comments[1].is_reply is True
    assert comments[1].parent_comment_id == "abc"
    assert comments[1].published_at == datetime(2026, 1, 1, 16, 0, tzinfo=UTC)


def test_max_replies_cap() -> None:
    data = json.loads(
        (Path(__file__).parent / "fixtures" / "initial_data_comments_min.json").read_text(encoding="utf-8")
    )
    comments = extract_comments_from_initial_data(data, max_replies_per_thread=0)
    assert len(comments) == 1


def test_continuation_tokens_present_in_renderer() -> None:
    blob = {"continuationItemRenderer": {"continuationEndpoint": {"continuationCommand": {"token": "TOKEN123"}}}}
    assert extract_continuation_tokens(blob) == ["TOKEN123"]


def test_extract_comments_entity_mutations_top_and_reply() -> None:
    now_utc = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    data = json.loads(
        (Path(__file__).parent / "fixtures" / "next_comments_entity_batch.json").read_text(encoding="utf-8")
    )
    all_c = extract_comments_from_entity_mutations(data, include_replies=True, now_utc=now_utc)
    assert len(all_c) == 2
    assert all_c[0].comment_id == "UgxEntityTopCommentIdAA"
    assert all_c[0].is_reply is False
    assert all_c[0].like_count == 11
    assert all_c[0].published_at == datetime(2026, 1, 2, 11, 0, tzinfo=UTC)
    assert all_c[1].comment_id == "UgxEntityTopCommentIdAA.childsuffix"
    assert all_c[1].is_reply is True
    assert all_c[1].parent_comment_id == "UgxEntityTopCommentIdAA"
    assert all_c[1].like_count == 1500
    assert all_c[1].published_at == datetime(2026, 1, 2, 11, 5, tzinfo=UTC)
    top_only = extract_comments_from_entity_mutations(data, include_replies=False, now_utc=now_utc)
    assert len(top_only) == 1
    assert top_only[0].comment_id == "UgxEntityTopCommentIdAA"


def test_response_has_comment_entities() -> None:
    assert response_has_comment_entities({"frameworkUpdates": {"entityBatchUpdate": {"mutations": [{}]}}}) is False
    assert (
        response_has_comment_entities(
            {"x": {"payload": {"commentEntityPayload": {"properties": {"commentId": "x"}}}}}
        )
        is True
    )


def test_extract_comment_records_from_response_merges_paths() -> None:
    data = json.loads(
        (Path(__file__).parent / "fixtures" / "initial_data_comments_min.json").read_text(encoding="utf-8")
    )
    merged = extract_comment_records_from_response(
        data,
        max_replies_per_thread=None,
        include_replies=True,
    )
    assert len(merged) == 2
    assert {c.comment_id for c in merged} == {"abc", "def"}
