"""Unit tests for Return YouTube Dislike vote parsing (documented GET /votes)."""

from youtube_scrape.domain.return_youtube_dislike_fetch import (
    parse_ryd_votes_payload,
    ryd_votes_url,
)


def test_parse_ryd_votes_typical_documented_shape() -> None:
    likes, dislikes = parse_ryd_votes_payload(
        {"id": "kxOuG8jMIgI", "likes": 27326, "dislikes": 498153},
    )
    assert likes == 27326
    assert dislikes == 498153


def test_parse_ryd_votes_missing() -> None:
    assert parse_ryd_votes_payload({}) == (None, None)
    assert parse_ryd_votes_payload("not-json") == (None, None)


def test_parse_ryd_rejects_negative() -> None:
    assert parse_ryd_votes_payload({"likes": -1}) == (None, None)


def test_ryd_votes_query_encodes_special_chars() -> None:
    url = ryd_votes_url("kxOuG8jMIgI", base_url="https://returnyoutubedislikeapi.com")
    assert url == "https://returnyoutubedislikeapi.com/votes?videoId=kxOuG8jMIgI"
