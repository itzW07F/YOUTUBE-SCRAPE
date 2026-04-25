from youtube_scrape.domain.innertube import (
    extract_innertube_api_key,
    extract_innertube_context,
    next_endpoint,
)


def test_extract_api_key() -> None:
    html = '<html><script>foo = {"INNERTUBE_API_KEY": "abc123"};</script></html>'
    assert extract_innertube_api_key(html) == "abc123"


def test_extract_context() -> None:
    html = '<html><script>foo = {"INNERTUBE_CONTEXT": {"client": {"gl": "US"}}};</script></html>'
    ctx = extract_innertube_context(html)
    assert ctx["client"]["gl"] == "US"


def test_next_endpoint() -> None:
    assert next_endpoint("K").endswith("?key=K")
