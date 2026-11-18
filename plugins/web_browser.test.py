"""Unit tests for web fact extraction and source URL validation."""

import pytest
from pydantic import ValidationError

from plugins.web_browser import WebBrowser

HTML = """
<html>
  <head><title>Python 3.13</title><style>.hidden{}</style></head>
  <body>
    <script>window.alert('not a fact')</script>
    <p>Python 3.13 ships a new interactive REPL.</p>
    <p>It also improves error messages.</p>
  </body>
</html>
"""


class FakeFetcher:
    def __init__(self, html=HTML, error=None):
        self.html = html
        self.error = error
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.html


def _payload(url="https://example.com/python") -> dict:
    return {
        "url": url,
        "topic_category": "PYTHON",
        "relevance_to_user": "Useful for local automation.",
    }


def _public_resolver(host):
    return ["93.184.216.34"]


def test_extracts_title_and_readable_summary():
    fetcher = FakeFetcher()
    plugin = WebBrowser(fetcher=fetcher, resolver=_public_resolver)
    assert plugin.initialize({}) is True

    result = plugin.execute(_payload())

    assert result.success is True
    assert fetcher.urls == ["https://example.com/python"]
    assert result.data["title"] == "Python 3.13"
    assert "new interactive REPL" in result.data["content_summary"]
    assert "window.alert" not in result.data["content_summary"]
    assert result.data["url"] == "https://example.com/python"
    assert result.data["topic_category"] == "PYTHON"


@pytest.mark.parametrize("url", ["ftp://example.com", "example.com", "file:///etc/passwd"])
def test_rejects_non_http_source_urls(url):
    plugin = WebBrowser(fetcher=FakeFetcher())
    plugin.initialize({})

    with pytest.raises(ValidationError):
        plugin.execute(_payload(url))


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "http://10.0.0.5/private",
        "http://localhost/private",
        "http://[::1]/private",
        "http://169.254.1.1/private",
    ],
)
def test_blocks_private_and_loopback_targets(url):
    fetcher = FakeFetcher()
    plugin = WebBrowser(fetcher=fetcher)
    plugin.initialize({})

    result = plugin.execute(_payload(url))

    assert result.success is False
    assert "not allowed" in result.error_message.lower()
    assert fetcher.urls == []


def test_blocks_hostname_that_resolves_to_a_private_address():
    fetcher = FakeFetcher()
    plugin = WebBrowser(fetcher=fetcher, resolver=lambda host: ["10.0.0.7"])
    plugin.initialize({})

    result = plugin.execute(_payload("https://internal.example/x"))

    assert result.success is False
    assert "not allowed" in result.error_message.lower()
    assert fetcher.urls == []


def test_blocks_hostname_when_dns_resolution_fails():
    def resolver(host):
        raise OSError("dns down")

    fetcher = FakeFetcher()
    plugin = WebBrowser(fetcher=fetcher, resolver=resolver)
    plugin.initialize({})

    result = plugin.execute(_payload("https://unknown.example/x"))

    assert result.success is False
    assert fetcher.urls == []


def test_allows_hostname_that_resolves_to_a_public_address():
    fetcher = FakeFetcher()
    plugin = WebBrowser(fetcher=fetcher, resolver=_public_resolver)
    plugin.initialize({})

    result = plugin.execute(_payload("https://public.example/x"))

    assert result.success is True
    assert fetcher.urls == ["https://public.example/x"]


def test_reports_fetch_failure_as_plugin_failure():
    plugin = WebBrowser(
        fetcher=FakeFetcher(error=RuntimeError("network down")),
        resolver=_public_resolver,
    )
    plugin.initialize({})

    result = plugin.execute(_payload())

    assert result.success is False
    assert "network down" in result.error_message