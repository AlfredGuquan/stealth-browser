"""Unit tests for stealth_browser.daemon."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from stealth_browser.daemon import DaemonHandler, is_daemon_running


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.navigate = AsyncMock(return_value={
        "url": "https://example.com/",
        "title": "Example",
        "login_redirect": False,
    })
    engine.snapshot = AsyncMock(return_value="page content")
    engine.click = AsyncMock(return_value="clicked #btn")
    engine.fill = AsyncMock(return_value="filled #input with 5 chars")
    engine.type_text = AsyncMock(return_value="typed 3 chars")
    engine.scroll = AsyncMock(return_value="scrolled down 3 steps")
    engine.upload = AsyncMock(return_value="uploaded /tmp/f.png")
    engine.screenshot = AsyncMock(return_value="/tmp/shot.png")
    engine.eval_js = AsyncMock(return_value="42")
    engine.get_info = AsyncMock(return_value="Example Domain")
    engine.status = AsyncMock(return_value={"browser_connected": True})
    engine.solve_captcha = AsyncMock(return_value={"solved": True, "message": "ok"})
    engine.shutdown = AsyncMock()
    engine.page = MagicMock()
    engine.page.url = "https://example.com/"
    engine.inject_cookies = AsyncMock(return_value=5)
    return engine


@pytest.fixture
def handler(mock_engine):
    return DaemonHandler(mock_engine, "test-session")


class TestDaemonHandler:
    @pytest.mark.asyncio
    async def test_open(self, handler, mock_engine):
        result = await handler.handle({"command": "open", "url": "https://example.com"})
        assert result["status"] == "ok"
        mock_engine.navigate.assert_called_once()

    @pytest.mark.asyncio
    async def test_snapshot(self, handler):
        result = await handler.handle({"command": "snapshot"})
        assert result["status"] == "ok"
        assert result["content"] == "page content"

    @pytest.mark.asyncio
    async def test_click(self, handler):
        result = await handler.handle({"command": "click", "selector": "#btn"})
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_fill(self, handler):
        result = await handler.handle({
            "command": "fill", "selector": "#input", "text": "hello"
        })
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_type(self, handler):
        result = await handler.handle({"command": "type", "text": "abc"})
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_scroll(self, handler):
        result = await handler.handle({
            "command": "scroll", "direction": "down", "amount": 2
        })
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_screenshot(self, handler):
        result = await handler.handle({"command": "screenshot"})
        assert result["status"] == "ok"
        assert result["path"] == "/tmp/shot.png"

    @pytest.mark.asyncio
    async def test_eval(self, handler):
        result = await handler.handle({
            "command": "eval", "expression": "1+1"
        })
        assert result["status"] == "ok"
        assert result["value"] == "42"

    @pytest.mark.asyncio
    async def test_get(self, handler):
        result = await handler.handle({"command": "get", "what": "title"})
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_status(self, handler):
        result = await handler.handle({"command": "status"})
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_ping(self, handler):
        result = await handler.handle({"command": "ping"})
        assert result["status"] == "ok"
        assert result["message"] == "pong"

    @pytest.mark.asyncio
    async def test_unknown_command(self, handler):
        result = await handler.handle({"command": "bogus"})
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_captcha(self, handler):
        result = await handler.handle({"command": "captcha"})
        assert result["status"] == "ok"
        assert result["solved"] is True

    def test_idle_tracking(self, handler):
        import time
        handler.touch()
        assert handler.idle_seconds < 1.0


class TestIsDaemonRunning:
    def test_no_pid_file(self, tmp_path):
        with patch("stealth_browser.daemon.pid_path", return_value=tmp_path / "nope.pid"):
            assert is_daemon_running("test") is False

    def test_stale_pid(self, tmp_path):
        pid_file = tmp_path / "stale.pid"
        pid_file.write_text("999999999")  # Non-existent PID
        sock_file = tmp_path / "stale.sock"
        sock_file.touch()
        with (
            patch("stealth_browser.daemon.pid_path", return_value=pid_file),
            patch("stealth_browser.daemon.socket_path", return_value=sock_file),
        ):
            assert is_daemon_running("stale") is False
            assert not pid_file.exists()
