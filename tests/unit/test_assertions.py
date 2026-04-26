"""Unit tests for engine.assert_text / assert_element + daemon assert dispatch."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from stealth_browser.daemon import DaemonHandler
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
    mock_page.evaluate = AsyncMock(return_value=False)
    mock_page.frames = [mock_page]

    mock_behavior = MagicMock()
    mock_behavior.page = mock_page

    tab = MagicMock(spec=TabInfo)
    tab.page = mock_page
    tab.behavior = mock_behavior
    tab.captcha = MagicMock()

    e._tabs = {1: tab}
    e._active_tab_id = 1
    e._next_tab_id = 2
    return e


@pytest.fixture
def mock_engine_for_daemon():
    engine = MagicMock()
    engine.assert_text = AsyncMock(return_value={"passed": True, "text": "Hi"})
    engine.assert_element = AsyncMock(return_value={"passed": True, "selector": "h1", "count": 1})
    return engine


@pytest.fixture
def handler(mock_engine_for_daemon):
    return DaemonHandler(mock_engine_for_daemon, "test-session")


class TestAssertText:
    @pytest.mark.asyncio
    async def test_passed_when_text_present(self, engine):
        engine.page.evaluate = AsyncMock(return_value=True)
        result = await engine.assert_text("Hello")
        assert result == {"passed": True, "text": "Hello"}

    @pytest.mark.asyncio
    async def test_failed_when_text_missing(self, engine):
        engine.page.evaluate = AsyncMock(return_value=False)
        result = await engine.assert_text("Nope")
        assert result == {"passed": False, "text": "Nope"}

    @pytest.mark.asyncio
    async def test_quotes_safely(self, engine):
        """Quotes/apostrophes in target must not break the JS string literal."""
        captured = {}
        async def fake_eval(js):
            captured["js"] = js
            return False
        engine.page.evaluate = fake_eval
        await engine.assert_text("can't \"break\" me")
        # The JSON-encoded literal must appear unchanged in the JS source.
        assert "can\\'t" in captured["js"] or "can't" in captured["js"]
        assert "\\\"break\\\"" in captured["js"]


class TestAssertElement:
    @pytest.mark.asyncio
    async def test_passed_with_count(self, engine):
        engine.page.evaluate = AsyncMock(return_value=3)
        result = await engine.assert_element("button.primary")
        assert result == {"passed": True, "selector": "button.primary", "count": 3}

    @pytest.mark.asyncio
    async def test_failed_when_zero_matches(self, engine):
        engine.page.evaluate = AsyncMock(return_value=0)
        result = await engine.assert_element("h99")
        assert result["passed"] is False
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_ref_resolves_to_data_ref_attribute(self, engine):
        """@eN refs must map to [data-ref="@eN"] CSS, not be passed verbatim."""
        captured = {}
        async def fake_eval(js, css):
            captured["css"] = css
            return 1
        engine.page.evaluate = fake_eval
        await engine.assert_element("@e5")
        assert captured["css"] == '[data-ref="@e5"]'


class TestDaemonAssert:
    @pytest.mark.asyncio
    async def test_pass_returns_ok(self, handler, mock_engine_for_daemon):
        mock_engine_for_daemon.assert_text = AsyncMock(return_value={
            "passed": True, "text": "Hello"
        })
        result = await handler.handle({
            "command": "assert", "kind": "text", "target": "Hello"
        })
        assert result["status"] == "ok"
        assert result["passed"] is True
        assert "PASS" in result["message"]

    @pytest.mark.asyncio
    async def test_fail_returns_assertion_failed(self, handler, mock_engine_for_daemon):
        mock_engine_for_daemon.assert_text = AsyncMock(return_value={
            "passed": False, "text": "Nope"
        })
        result = await handler.handle({
            "command": "assert", "kind": "text", "target": "Nope"
        })
        assert result["status"] == "error"
        assert result["code"] == "ASSERTION_FAILED"
        assert result["retryable"] is False
        assert result["passed"] is False

    @pytest.mark.asyncio
    async def test_unknown_kind_is_usage_error(self, handler):
        result = await handler.handle({
            "command": "assert", "kind": "bogus", "target": "X"
        })
        assert result["code"] == "USAGE"

    @pytest.mark.asyncio
    async def test_element_dispatches_to_assert_element(self, handler, mock_engine_for_daemon):
        mock_engine_for_daemon.assert_element = AsyncMock(return_value={
            "passed": True, "selector": "h1", "count": 1
        })
        result = await handler.handle({
            "command": "assert", "kind": "element", "target": "h1"
        })
        assert result["status"] == "ok"
        mock_engine_for_daemon.assert_element.assert_awaited_once_with("h1")

    @pytest.mark.asyncio
    async def test_batch_short_circuits_on_assertion_failure(self, handler, mock_engine_for_daemon):
        """Batch must stop at the failed assertion and surface its code."""
        mock_engine_for_daemon.assert_text = AsyncMock(return_value={
            "passed": False, "text": "Missing"
        })
        result = await handler.handle({
            "command": "batch",
            "commands": [
                {"command": "assert", "kind": "text", "target": "Missing"},
            ],
        })
        assert result["status"] == "error"
        assert result["code"] == "ASSERTION_FAILED"
        assert result["failed_index"] == 0
