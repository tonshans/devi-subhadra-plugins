"""Fetch a web page and extract a JSON-ready fact summary."""

from __future__ import annotations

import ipaddress
import socket
from html.parser import HTMLParser
from typing import Callable, Optional
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import Field

from core.base_plugin import BaseAgentPlugin
from core.schemas import PluginOutputSchema, StrictBaseModel


class BrowseInput(StrictBaseModel):
    url: str = Field(..., pattern=r"^https?://.+")
    topic_category: str = Field(..., min_length=2)
    relevance_to_user: str = Field(..., min_length=5)


Resolver = Callable[[str], list[str]]


def _resolve(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _blocked_url(url: str, resolver: Resolver = _resolve) -> bool:
    """Block literal and DNS-resolved private targets; fail closed on DNS errors."""
    host = urlsplit(url).hostname
    if not host:
        return True
    host = host.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    try:
        addresses = resolver(host)
    except OSError:
        return True
    return not addresses or any(
        not ipaddress.ip_address(address).is_global for address in addresses
    )


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in {"script", "style"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self._parts).split())


class WebBrowser(BaseAgentPlugin):
    plugin_name = "web_browser"
    description = "Browse a URL, extract readable facts, and return a discovery record."
    input_schema = BrowseInput

    def __init__(
        self,
        fetcher: Optional[Callable[[str], str]] = None,
        resolver: Optional[Resolver] = None,
    ) -> None:
        self._fetcher = fetcher
        self._resolver = resolver or _resolve

    def initialize(self, config: dict) -> bool:
        return True

    def _default_fetch(self, url: str) -> str:
        request = Request(url, headers={"User-Agent": "devi-subhadra/0.1"})
        with urlopen(request, timeout=15) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")

    def execute(self, payload: dict) -> PluginOutputSchema:
        request = BrowseInput.model_validate(payload)
        if _blocked_url(request.url, self._resolver):
            return PluginOutputSchema(
                success=False,
                data={},
                error_message=f"URL not allowed: {request.url}",
            )

        try:
            html = (self._fetcher or self._default_fetch)(request.url)
        except Exception as exc:
            return PluginOutputSchema(
                success=False, data={}, error_message=f"Fetch failed: {exc}"
            )

        extractor = _TextExtractor()
        extractor.feed(html)
        summary = extractor.text()[:400]

        return PluginOutputSchema(
            success=True,
            data={
                "url": request.url,
                "title": " ".join(extractor.title.split()),
                "content_summary": summary,
                "topic_category": request.topic_category,
                "relevance_to_user": request.relevance_to_user,
            },
        )

    def shutdown(self) -> None:
        return None