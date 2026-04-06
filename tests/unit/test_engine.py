"""Unit tests for stealth_browser.engine."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from stealth_browser.engine import StealthEngine


@pytest.fixture
def engine():
    """Create an engine with mocked browser internals."""
    e = StealthEngine()
    e.playwright = MagicMock()
    e.browser = MagicMock()
    e.browser.is_connected.return_value = True
    e.context = AsyncMock()
    e.page = AsyncMock()
    e.page.url = "https://example.com/"
    e.page.title = AsyncMock(return_value="Example Domain")
    e.page.evaluate = AsyncMock(return_value="test value")
    e.behavior = MagicMock()
    e.behavior.click = AsyncMock()
    e.behavior.fill = AsyncMock()
    e.behavior.type_text = AsyncMock()
    e.behavior.scroll = AsyncMock()
    e.captcha = MagicMock()
    return e


class TestStatus:
    @pytest.mark.asyncio
    async def test_status_alive(self, engine):
        result = await engine.status()
        assert result["browser_connected"] is True
        assert result["current_url"] == "https://example.com/"

    def test_is_alive(self, engine):
        assert engine.is_alive is True


class TestGetInfo:
    @pytest.mark.asyncio
    async def test_get_url(self, engine):
        result = await engine.get_info("url")
        assert result == "https://example.com/"

    @pytest.mark.asyncio
    async def test_get_title(self, engine):
        result = await engine.get_info("title")
        assert result == "Example Domain"

    @pytest.mark.asyncio
    async def test_get_text(self, engine):
        engine.page.evaluate = AsyncMock(return_value="page text content")
        result = await engine.get_info("text")
        assert result == "page text content"

    @pytest.mark.asyncio
    async def test_get_invalid(self, engine):
        with pytest.raises(ValueError, match="unknown info type"):
            await engine.get_info("invalid")


class TestClick:
    @pytest.mark.asyncio
    async def test_click(self, engine):
        result = await engine.click("#btn")
        engine.behavior.click.assert_called_once_with("#btn")
        assert "clicked" in result


class TestFill:
    @pytest.mark.asyncio
    async def test_fill(self, engine):
        result = await engine.fill("#input", "hello")
        engine.behavior.fill.assert_called_once_with("#input", "hello")
        assert "5 chars" in result


class TestEvalJs:
    @pytest.mark.asyncio
    async def test_eval(self, engine):
        result = await engine.eval_js("1 + 1")
        engine.page.evaluate.assert_called_once_with("1 + 1")


class TestUpload:
    @pytest.mark.asyncio
    async def test_upload(self, engine):
        locator = AsyncMock()
        engine.page.locator = MagicMock(return_value=locator)
        result = await engine.upload('input[type="file"]', "/tmp/test.png")
        locator.set_input_files.assert_called_once_with("/tmp/test.png")


class TestNavigate:
    @pytest.mark.asyncio
    async def test_navigate_basic(self, engine):
        engine.page.goto = AsyncMock()
        engine.page.wait_for_timeout = AsyncMock()
        engine.page.url = "https://example.com/"
        engine.page.title = AsyncMock(return_value="Example")

        result = await engine.navigate("https://example.com/")
        assert result["url"] == "https://example.com/"
        assert result["title"] == "Example"
        assert result["login_redirect"] is False

    @pytest.mark.asyncio
    async def test_navigate_login_redirect(self, engine):
        engine.page.goto = AsyncMock()
        engine.page.wait_for_timeout = AsyncMock()
        engine.page.url = "https://example.com/login"
        engine.page.title = AsyncMock(return_value="Login")
        engine._current_site = None

        # Without site param, login redirect is not re-attempted
        result = await engine.navigate("https://example.com/dashboard")
        assert result["login_redirect"] is False  # No site -> no redirect detection
