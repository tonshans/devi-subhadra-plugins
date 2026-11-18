"""
Fetch JS-rendered web pages via Browserless.io REST API (/content).
add BROWSERLESS_API_KEY to .env
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from html.parser import HTMLParser
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

import httpx
from pydantic import Field

from core.base_plugin import BaseAgentPlugin
from core.config_loader import SecretNotFoundError, SecretsManager
from core.schemas import PluginOutputSchema, StrictBaseModel

DEFAULT_ENDPOINT = "https://production-sfo.browserless.io/content"
MAX_CONTENT_CHARS = 8000

Resolver = Callable[[str], list[str]]


class BrowserlessInput(StrictBaseModel):
    url: str = Field(..., pattern=r"^https?://.+")


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
        not ipaddress.ip_address(addr).is_global for addr in addresses
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
        elif tag in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self._parts).split())


class BrowserlessBrowser(BaseAgentPlugin):
    plugin_name = "browserless_browser"
    description = (
        "Browse internet and open web pages that require JavaScript rendering via "
        "Browserless.io and extract the main text."
    )
    input_schema = BrowserlessInput

    def __init__(
        self,
        *,
        client: Optional[httpx.AsyncClient] = None,
        secrets: Optional[SecretsManager] = None,
        resolver: Optional[Resolver] = None,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout: float = 30.0,
    ) -> None:
        self._client = client
        self._secrets = secrets
        self._resolver = resolver or _resolve
        self._endpoint = endpoint
        self._timeout = timeout

    def initialize(self, config: dict[str, Any]) -> bool:
        if self._secrets is None:
            self._secrets = SecretsManager()
        return True

    async def _post(self, token: str, payload: dict[str, Any]) -> httpx.Response:
        params = {"token": token}
        if self._client is not None:
            return await self._client.post(
                self._endpoint, params=params, json=payload
            )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.post(
                self._endpoint, params=params, json=payload
            )

    async def execute(self, payload: dict[str, Any]) -> PluginOutputSchema:
        request = self.input_schema.model_validate(payload)
        if self._secrets is None:
            return PluginOutputSchema(
                success=False,
                data={},
                error_message="BrowserlessBrowser is not initialized.",
            )
        if await asyncio.to_thread(_blocked_url, request.url, self._resolver):
            return PluginOutputSchema(
                success=False,
                data={},
                error_message=f"URL not allowed: {request.url}",
            )

        try:
            token = self._secrets.get_secret("BROWSERLESS_API_KEY")
        except SecretNotFoundError as exc:
            return PluginOutputSchema(
                success=False, data={}, error_message=str(exc)
            )

        body = {
            "url": request.url,
            "gotoOptions": {"waitUntil": "networkidle2"},
        }
        # Token lives in the query string, so never forward httpx errors verbatim.
        try:
            response = await self._post(token, body)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return PluginOutputSchema(
                success=False,
                data={"url": request.url},
                assertions_passed=False,
                error_message=f"Browserless API HTTP {exc.response.status_code}",
            )
        except httpx.HTTPError as exc:
            return PluginOutputSchema(
                success=False,
                data={"url": request.url},
                assertions_passed=False,
                error_message=f"Browserless request failed: {type(exc).__name__}",
            )

        extractor = _TextExtractor()
        extractor.feed(response.text)
        title = " ".join(extractor.title.split())
        content = extractor.text()[:MAX_CONTENT_CHARS]
        if not content:
            return PluginOutputSchema(
                success=False,
                data={"url": request.url, "title": title},
                assertions_passed=False,
                error_message="Browserless returned no readable text.",
            )

        return PluginOutputSchema(
            success=True,
            data={"url": request.url, "title": title, "content": content},
            assertions_passed=True,
        )

    def shutdown(self) -> None:
        return None
