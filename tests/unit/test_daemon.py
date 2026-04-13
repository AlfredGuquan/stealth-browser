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

    # V2 methods
    engine.select_option = AsyncMock(return_value="selected 'v1' on #sel")
    engine.check = AsyncMock(return_value="checked #cb")
    engine.uncheck = AsyncMock(return_value="unchecked #cb")
    engine.wait_for_element = AsyncMock(return_value="element #el is visible")
    engine.wait_for_text = AsyncMock(return_value="text 'Hello' found")
    engine.wait_for_network_idle = AsyncMock(return_value="network idle")
    engine.wait_for_timeout = AsyncMock(return_value="waited 1000ms")
    engine.wait_for_url_pattern = AsyncMock(return_value="https://example.com/")
    engine.screenshot_annotated = AsyncMock(return_value={
        "path": "/tmp/annot.png",
        "legend": [{"ref": "@e0", "tag": "button", "text": "Submit"}],
    })
    engine.dialog_accept = AsyncMock(return_value="dialog accepted")
    engine.dialog_dismiss = AsyncMock(return_value="dialog dismissed")
    engine.dialog_info = MagicMock(return_value={"present": False})
    engine.go_back = AsyncMock(return_value={"url": "https://example.com/back", "title": "Back"})
    engine.go_forward = AsyncMock(return_value={"url": "https://example.com/fwd", "title": "Forward"})
    engine.reload = AsyncMock(return_value={"url": "https://example.com/", "title": "Reloaded"})
    engine.tab_list = AsyncMock(return_value=[{"tab_id": 1, "url": "https://example.com/", "title": "Example", "active": True}])
    engine.tab_create = AsyncMock(return_value={"tab_id": 2})
    engine.tab_switch = MagicMock(return_value="switched to tab 2")
    engine.tab_close = AsyncMock(return_value="closed tab 1")
    engine.set_auto_dismiss = MagicMock(return_value="dialog auto-dismiss on")
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


class TestSelectCheckCommands:
    """F10: select, check, uncheck via daemon."""

    @pytest.mark.asyncio
    async def test_select(self, handler, mock_engine):
        result = await handler.handle({
            "command": "select", "selector": "#dropdown", "value": "opt1"
        })
        assert result["status"] == "ok"
        mock_engine.select_option.assert_called_once_with("#dropdown", "opt1")

    @pytest.mark.asyncio
    async def test_check(self, handler, mock_engine):
        result = await handler.handle({"command": "check", "selector": "#cb"})
        assert result["status"] == "ok"
        mock_engine.check.assert_called_once_with("#cb")

    @pytest.mark.asyncio
    async def test_uncheck(self, handler, mock_engine):
        result = await handler.handle({"command": "uncheck", "selector": "#cb"})
        assert result["status"] == "ok"
        mock_engine.uncheck.assert_called_once_with("#cb")


class TestWaitCommands:
    """F7: wait commands via daemon."""

    @pytest.mark.asyncio
    async def test_wait_element(self, handler, mock_engine):
        result = await handler.handle({
            "command": "wait", "type": "element", "target": "#el"
        })
        assert result["status"] == "ok"
        mock_engine.wait_for_element.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_text(self, handler, mock_engine):
        result = await handler.handle({
            "command": "wait", "type": "text", "target": "Hello"
        })
        assert result["status"] == "ok"
        mock_engine.wait_for_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_network_idle(self, handler, mock_engine):
        result = await handler.handle({
            "command": "wait", "type": "network-idle"
        })
        assert result["status"] == "ok"
        mock_engine.wait_for_network_idle.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_timeout(self, handler, mock_engine):
        result = await handler.handle({
            "command": "wait", "type": "timeout", "target": "500"
        })
        assert result["status"] == "ok"
        mock_engine.wait_for_timeout.assert_called_once_with(500)

    @pytest.mark.asyncio
    async def test_wait_unknown_type(self, handler):
        result = await handler.handle({
            "command": "wait", "type": "bogus"
        })
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_wait_unknown_type_lists_valid_types(self, handler):
        """Error message for unknown wait type must list valid options."""
        result = await handler.handle({
            "command": "wait", "type": "bogus"
        })
        assert result["status"] == "error"
        err = result["error"]
        assert "element" in err
        assert "text" in err
        assert "network-idle" in err
        assert "timeout" in err
        assert "url" in err

    @pytest.mark.asyncio
    async def test_wait_missing_type_lists_valid_types(self, handler):
        """Missing type key (e.g. batch sends 'kind' instead of 'type') → same helpful error."""
        result = await handler.handle({
            "command": "wait", "kind": "network-idle"
        })
        assert result["status"] == "error"
        err = result["error"]
        assert "element" in err


class TestDialogCommands:
    """F8: dialog commands via daemon."""

    @pytest.mark.asyncio
    async def test_dialog_accept(self, handler, mock_engine):
        result = await handler.handle({
            "command": "dialog", "action": "accept"
        })
        assert result["status"] == "ok"
        mock_engine.dialog_accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_dialog_accept_with_text(self, handler, mock_engine):
        result = await handler.handle({
            "command": "dialog", "action": "accept", "text": "hi"
        })
        assert result["status"] == "ok"
        mock_engine.dialog_accept.assert_called_once_with("hi")

    @pytest.mark.asyncio
    async def test_dialog_dismiss(self, handler, mock_engine):
        result = await handler.handle({
            "command": "dialog", "action": "dismiss"
        })
        assert result["status"] == "ok"
        mock_engine.dialog_dismiss.assert_called_once()

    @pytest.mark.asyncio
    async def test_dialog_info(self, handler, mock_engine):
        result = await handler.handle({
            "command": "dialog", "action": "info"
        })
        assert result["status"] == "ok"
        assert result["present"] is False

    @pytest.mark.asyncio
    async def test_dialog_auto_dismiss(self, handler, mock_engine):
        result = await handler.handle({
            "command": "dialog", "action": "auto-dismiss", "enabled": True
        })
        assert result["status"] == "ok"
        mock_engine.set_auto_dismiss.assert_called_once_with(True)

    @pytest.mark.asyncio
    async def test_dialog_unknown_action(self, handler):
        result = await handler.handle({
            "command": "dialog", "action": "bogus"
        })
        assert result["status"] == "error"


class TestNavigationCommands:
    """F9: back, forward, reload via daemon."""

    @pytest.mark.asyncio
    async def test_back(self, handler, mock_engine):
        result = await handler.handle({"command": "back"})
        assert result["status"] == "ok"
        assert result["url"] == "https://example.com/back"
        mock_engine.go_back.assert_called_once()

    @pytest.mark.asyncio
    async def test_forward(self, handler, mock_engine):
        result = await handler.handle({"command": "forward"})
        assert result["status"] == "ok"
        assert result["url"] == "https://example.com/fwd"

    @pytest.mark.asyncio
    async def test_reload(self, handler, mock_engine):
        result = await handler.handle({"command": "reload"})
        assert result["status"] == "ok"
        assert result["title"] == "Reloaded"


class TestTabCommands:
    """F11: tab commands via daemon."""

    @pytest.mark.asyncio
    async def test_tab_list(self, handler, mock_engine):
        result = await handler.handle({"command": "tab", "action": "list"})
        assert result["status"] == "ok"
        assert len(result["tabs"]) == 1

    @pytest.mark.asyncio
    async def test_tab_create(self, handler, mock_engine):
        result = await handler.handle({"command": "tab", "action": "create"})
        assert result["status"] == "ok"
        assert result["tab_id"] == 2

    @pytest.mark.asyncio
    async def test_tab_create_with_url(self, handler, mock_engine):
        mock_engine.tab_create = AsyncMock(return_value={
            "tab_id": 2, "url": "https://example.com/", "title": "Example"
        })
        result = await handler.handle({
            "command": "tab", "action": "create", "url": "https://example.com/"
        })
        assert result["status"] == "ok"
        assert result["url"] == "https://example.com/"

    @pytest.mark.asyncio
    async def test_tab_switch(self, handler, mock_engine):
        result = await handler.handle({
            "command": "tab", "action": "switch", "tab_id": 2
        })
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_tab_close(self, handler, mock_engine):
        result = await handler.handle({
            "command": "tab", "action": "close", "tab_id": 1
        })
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_tab_unknown_action(self, handler):
        result = await handler.handle({
            "command": "tab", "action": "bogus"
        })
        assert result["status"] == "error"


class TestBatchCommand:
    """F13: batch command execution."""

    @pytest.mark.asyncio
    async def test_batch_success(self, handler, mock_engine):
        result = await handler.handle({
            "command": "batch",
            "commands": [
                {"command": "click", "selector": "#btn"},
                {"command": "screenshot"},
            ],
            "fast": True,
        })
        assert result["status"] == "ok"
        assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_batch_stops_on_error(self, handler, mock_engine):
        mock_engine.click = AsyncMock(side_effect=Exception("element not found"))
        result = await handler.handle({
            "command": "batch",
            "commands": [
                {"command": "click", "selector": "#bad"},
                {"command": "screenshot"},
            ],
            "fast": True,
        })
        # The click raises an exception, so it should be caught and returned
        # as an error result in the batch
        assert result["status"] == "error"
        assert result["failed_index"] == 0

    @pytest.mark.asyncio
    async def test_batch_empty(self, handler):
        result = await handler.handle({
            "command": "batch", "commands": [], "fast": True,
        })
        assert result["status"] == "ok"
        assert result["results"] == []


class TestV3Commands:
    """V3: F14 (skip_cookies), F15 (wait url), F16 (screenshot --annotate)."""

    @pytest.mark.asyncio
    async def test_open_forwards_skip_cookies(self, handler, mock_engine):
        await handler.handle({
            "command": "open",
            "url": "http://localhost:3000/",
            "site": "localhost",
            "skip_cookies": True,
        })
        _, kwargs = mock_engine.navigate.call_args
        assert kwargs.get("skip_cookies") is True

    @pytest.mark.asyncio
    async def test_open_defaults_skip_cookies_false(self, handler, mock_engine):
        await handler.handle({
            "command": "open",
            "url": "https://example.com/",
            "site": "example.com",
        })
        _, kwargs = mock_engine.navigate.call_args
        assert kwargs.get("skip_cookies") is False

    @pytest.mark.asyncio
    async def test_wait_url(self, handler, mock_engine):
        result = await handler.handle({
            "command": "wait",
            "type": "url",
            "target": "**example.com**",
            "timeout": 5000,
        })
        assert result["status"] == "ok"
        mock_engine.wait_for_url_pattern.assert_called_once_with(
            "**example.com**", timeout=5000
        )

    @pytest.mark.asyncio
    async def test_wait_url_timeout_surfaces_as_error(self, handler, mock_engine):
        mock_engine.wait_for_url_pattern = AsyncMock(
            side_effect=TimeoutError("timeout waiting for url pattern: **/x")
        )
        result = await handler.handle({
            "command": "wait",
            "type": "url",
            "target": "**/x",
            "timeout": 500,
        })
        assert result["status"] == "error"
        assert "timeout" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_screenshot_annotate(self, handler, mock_engine):
        result = await handler.handle({
            "command": "screenshot",
            "annotate": True,
        })
        assert result["status"] == "ok"
        assert result["path"] == "/tmp/annot.png"
        assert result["legend"][0]["ref"] == "@e0"
        mock_engine.screenshot_annotated.assert_called_once()

    @pytest.mark.asyncio
    async def test_screenshot_default_path_unchanged(self, handler, mock_engine):
        """Without --annotate, the dispatch must still hit plain screenshot()."""
        result = await handler.handle({"command": "screenshot"})
        assert result["status"] == "ok"
        assert result["path"] == "/tmp/shot.png"
        mock_engine.screenshot_annotated.assert_not_called()


class TestIsDaemonRunning:
    def test_no_pid_file(self, tmp_path):
        with patch("stealth_browser.daemon.pid_path", return_value=tmp_path / "nope.pid"):
            assert is_daemon_running("test") is False

    def test_stale_pid(self, tmp_path):
        pid_file = tmp_path / "stale.pid"
        pid_file.write_text("999999999")
        sock_file = tmp_path / "stale.sock"
        sock_file.touch()
        with (
            patch("stealth_browser.daemon.pid_path", return_value=pid_file),
            patch("stealth_browser.daemon.socket_path", return_value=sock_file),
        ):
            assert is_daemon_running("stale") is False
            assert not pid_file.exists()
