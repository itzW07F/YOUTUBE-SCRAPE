from youtube_scrape.domain.captions_convert import (
    timedtext_json3_to_plain,
    timedtext_xml_to_plain,
    timedtext_xml_to_webvtt,
)


def test_json3_to_plain() -> None:
    data = {
        "events": [
            {"segs": [{"utf8": "Hello "}, {"utf8": "world"}]},
            {"segs": [{"utf8": "Next line"}]},
        ]
    }
    assert timedtext_json3_to_plain(data) == "Hello world\nNext line"


def test_plain_from_xml() -> None:
    xml = """<?xml version="1.0" encoding="utf-8" ?>
<transcript>
<text start="0" dur="1">Hello</text>
<text start="1" dur="1">World</text>
</transcript>
"""
    assert timedtext_xml_to_plain(xml) == "Hello\nWorld"


def test_webvtt_from_xml() -> None:
    xml = """<?xml version="1.0" encoding="utf-8" ?>
<transcript>
<text start="0.5" dur="1.0">Hi</text>
</transcript>
"""
    out = timedtext_xml_to_webvtt(xml)
    assert out.startswith("WEBVTT")
    assert "Hi" in out
