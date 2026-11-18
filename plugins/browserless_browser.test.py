import httpx
import pytest

from plugins.browserless_browser import BrowserlessBrowser


class _FakeSecrets:
    def __init__(self, token: str) -> None:
        self._token = token

    def get_secret(self, key: str) -> str:
        assert key == "BROWSERLESS_API_KEY"
        return self._token


@pytest.mark.asyncio
async def test_browserless_extracts_rendered_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["token"] == "secret-tok"
        return httpx.Response(
            200,
            text="<html><head><title>Demo</title></head>"
            "<body><script>ignore()</script><p>Hello JS</p></body></html>",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        plugin = BrowserlessBrowser(
            client=client,
            secrets=_FakeSecrets("secret-tok"),
            resolver=lambda _: ["93.184.216.34"],
        )
        plugin.initialize({})
        out = await plugin.execute({"url": "https://example.com"})

    assert out.success is True
    assert out.data["title"] == "Demo"
    assert out.data["content"] == "Hello JS"


@pytest.mark.asyncio
async def test_browserless_never_leaks_token_on_error() -> None:
    secret = "super-secret-browserless-token"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        plugin = BrowserlessBrowser(
            client=client,
            secrets=_FakeSecrets(secret),
            resolver=lambda _: ["93.184.216.34"],
        )
        plugin.initialize({})
        out = await plugin.execute({"url": "https://example.com"})

    assert out.success is False
    assert secret not in (out.error_message or "")


@pytest.mark.asyncio
async def test_browserless_blocks_private_targets() -> None:
    plugin = BrowserlessBrowser(secrets=_FakeSecrets("tok"))
    plugin.initialize({})
    out = await plugin.execute({"url": "http://127.0.0.1/admin"})
    assert out.success is False
    assert "not allowed" in (out.error_message or "").lower()
