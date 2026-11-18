import pytest
from unittest.mock import patch, AsyncMock
from plugins.headless_browser import HeadlessBrowserPlugin

@pytest.mark.asyncio
@patch('plugins.headless_browser.async_playwright')
async def test_headless_browser_threads_search(mock_playwright):
    # Mocking Playwright Browser, Context, dan Page
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()

    mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright)
    mock_playwright.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page

    # Mocking hasil ekstraksi teks dari browser
    mock_page.evaluate.return_value = [
        "Post 1: AI is evolving rapidly on Threads!",
        "Post 2: Just deployed a new autonomous agent."
    ]

    plugin = HeadlessBrowserPlugin()
    plugin.initialize({})

    # Eksekusi plugin dengan target Threads
    payload = {"platform": "threads", "query": "autonomous agent"}
    result = await plugin.execute(payload)

    # Assertion-Driven Check
    assert result.success is True
    assert len(result.data["posts"]) == 2
    assert "AI is evolving" in result.data["posts"][0]
    assert result.assertions_passed is True
