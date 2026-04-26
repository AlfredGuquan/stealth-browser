"""Unit tests for engine.visible_text -- post-scroll viewport text helper."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from stealth_browser.engine import StealthEngine, TabInfo


@pytest.fixture
def engine():
    e = StealthEngine()
    e.playwright = MagicMock()
    e.browser = MagicMock()
    e.browser.is_connected.return_value = True
    e.context = AsyncMock()

    mock_page = AsyncMock()
    mock_page.url = "https://example.com/"
    mock_page.evaluate = AsyncMock(return_value="default")
    mock_page.frames = [mock_page]

    mock_behavior = MagicMock()
    mock_behavior.scroll = AsyncMock()
    mock_behavior.page = mock_page

    tab = MagicMock(spec=TabInfo)
    tab.page = mock_page
    tab.behavior = mock_behavior
    tab.captcha = MagicMock()

    e._tabs = {1: tab}
    e._active_tab_id = 1
    e._next_tab_id = 2
    return e


class TestVisibleText:
    """visible_text() extracts in-viewport text so agents can skip a screenshot+Read after scroll."""

    @pytest.mark.asyncio
    async def test_calls_page_evaluate(self, engine):
        engine.page.evaluate = AsyncMock(return_value="line A\nline B")
        result = await engine.visible_text()
        assert result == "line A\nline B"
        engine.page.evaluate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passes_max_chars_into_eval(self, engine):
        """max_chars must reach the JS so slicing happens page-side, not Python-side."""
        captured = {}
        async def fake_eval(js):
            captured["js"] = js
            return ""
        engine.page.evaluate = fake_eval
        await engine.visible_text(max_chars=500)
        assert "500" in captured["js"]

    @pytest.mark.asyncio
    async def test_raises_when_no_page(self, engine):
        engine._tabs = {}
        with pytest.raises(RuntimeError):
            await engine.visible_text()
