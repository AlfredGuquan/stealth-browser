"""Unit tests for stealth_browser.engine."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from stealth_browser.engine import StealthEngine, TabInfo


@pytest.fixture
def engine():
    """Create an engine with mocked browser internals.

    V2: page/behavior/captcha are now properties that read from _tabs,
    so we set up the tab dict directly.
    """
    e = StealthEngine()
    e.playwright = MagicMock()
    e.browser = MagicMock()
    e.browser.is_connected.return_value = True
    e.context = AsyncMock()

    # Create a mock TabInfo in the tabs dict
    mock_page = AsyncMock()
    mock_page.url = "https://example.com/"
    mock_page.title = AsyncMock(return_value="Example Domain")
    mock_page.evaluate = AsyncMock(return_value="test value")
    mock_page.frames = [mock_page]  # main frame is the page itself

    mock_behavior = MagicMock()
    mock_behavior.click = AsyncMock()
    mock_behavior.fill = AsyncMock()
    mock_behavior.type_text = AsyncMock()
    mock_behavior.scroll = AsyncMock()
    mock_behavior.page = mock_page

    mock_captcha = MagicMock()

    tab = MagicMock(spec=TabInfo)
    tab.page = mock_page
    tab.behavior = mock_behavior
    tab.captcha = mock_captcha

    e._tabs = {1: tab}
    e._active_tab_id = 1
    e._next_tab_id = 2
    return e


class TestStatus:
    @pytest.mark.asyncio
    async def test_status_alive(self, engine):
        result = await engine.status()
        assert result["browser_connected"] is True
        assert result["current_url"] == "https://example.com/"
        assert result["active_tab"] == 1
        assert result["tab_count"] == 1

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
        # click listener fires → success
        engine.page.evaluate = AsyncMock(side_effect=[
            None,   # inject listener
            True,   # check: listener fired
        ])
        result = await engine.click("#btn")
        engine.behavior.click.assert_called_once_with("#btn")
        assert "clicked" in result

    @pytest.mark.asyncio
    async def test_click_silent_failure(self, engine):
        """Click dispatched but event not received → raise error."""
        engine.page.evaluate = AsyncMock(side_effect=[
            None,   # inject listener
            False,  # check: listener did NOT fire
        ])
        # URL unchanged → no navigation either
        engine.page.url = "https://example.com/"
        with pytest.raises(RuntimeError, match="click not received"):
            await engine.click("#btn")

    @pytest.mark.asyncio
    async def test_click_navigated_skips_verify(self, engine):
        """Click triggers navigation (URL changed) → success even if listener missed."""
        url_before = "https://example.com/"
        url_after = "https://example.com/new-page"
        engine.page.url = url_before

        async def do_click(css):
            # Simulate navigation as side effect of click
            engine.page.url = url_after

        engine.behavior.click = AsyncMock(side_effect=do_click)
        engine.page.evaluate = AsyncMock(side_effect=[
            None,   # inject listener
            False,  # listener didn't fire (page navigated, listener lost)
        ])
        result = await engine.click("#link")
        assert "clicked" in result


class TestFill:
    @pytest.mark.asyncio
    async def test_fill(self, engine):
        result = await engine.fill("#input", "hello")
        engine.behavior.fill.assert_called_once_with("#input", "hello")
        assert "5 chars" in result

    @pytest.mark.asyncio
    async def test_fill_empty_returns_cleared(self, engine):
        result = await engine.fill("#input", "")
        engine.behavior.fill.assert_called_once_with("#input", "")
        assert "cleared" in result


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

        result = await engine.navigate("https://example.com/dashboard")
        assert result["login_redirect"] is False  # No site -> no redirect detection

    @pytest.mark.asyncio
    async def test_navigate_skip_cookies_bypasses_injection(self, engine):
        """F14: skip_cookies=True must not call inject_cookies."""
        engine.page.goto = AsyncMock()
        engine.page.wait_for_timeout = AsyncMock()
        engine.page.url = "http://localhost:3000/"
        engine.page.title = AsyncMock(return_value="Dev")
        engine.inject_cookies = AsyncMock(return_value=5)

        result = await engine.navigate(
            "http://localhost:3000/",
            site="localhost",
            skip_cookies=True,
        )
        engine.inject_cookies.assert_not_called()
        assert result["login_redirect"] is False

    @pytest.mark.asyncio
    async def test_navigate_skip_cookies_bypasses_login_redirect(self, engine):
        """F14: skip_cookies=True must not treat /login paths as session expired."""
        engine.page.goto = AsyncMock()
        engine.page.wait_for_timeout = AsyncMock()
        # After goto, the page lands on a URL that looks like a login page.
        engine.page.url = "http://localhost:3000/login"
        engine.page.title = AsyncMock(return_value="Dev Login")
        engine.inject_cookies = AsyncMock(return_value=0)

        result = await engine.navigate(
            "http://localhost:3000/login",
            site="localhost",
            skip_cookies=True,
        )
        # Must NOT flip login_redirect even though the URL matches the pattern
        assert result["login_redirect"] is False
        engine.inject_cookies.assert_not_called()


class TestWaitForUrlPattern:
    """F15: glob-based URL wait."""

    @pytest.mark.asyncio
    async def test_matches_current_url(self, engine):
        engine.page.wait_for_url = AsyncMock()
        engine.page.url = "https://example.com/"
        result = await engine.wait_for_url_pattern("**example.com**")
        engine.page.wait_for_url.assert_called_once_with(
            "**example.com**", timeout=30000
        )
        assert result == "https://example.com/"

    @pytest.mark.asyncio
    async def test_timeout_translates_to_clean_error(self, engine):
        from patchright.async_api import TimeoutError as PWTimeoutError
        engine.page.wait_for_url = AsyncMock(
            side_effect=PWTimeoutError("Timeout 1500ms exceeded.")
        )
        with pytest.raises(TimeoutError, match="timeout waiting for url pattern"):
            await engine.wait_for_url_pattern("**/never", timeout=1500)

    @pytest.mark.asyncio
    async def test_non_timeout_error_bubbles_up(self, engine):
        """Non-timeout failures should NOT be masked as 'timeout waiting for url'."""
        engine.page.wait_for_url = AsyncMock(
            side_effect=RuntimeError("page closed")
        )
        with pytest.raises(RuntimeError, match="page closed"):
            await engine.wait_for_url_pattern("**/x", timeout=1500)

    @pytest.mark.asyncio
    async def test_respects_custom_timeout(self, engine):
        engine.page.wait_for_url = AsyncMock()
        engine.page.url = "https://x.com/"
        await engine.wait_for_url_pattern("**x.com**", timeout=5000)
        engine.page.wait_for_url.assert_called_once_with(
            "**x.com**", timeout=5000
        )


class TestScreenshotAnnotated:
    """F16: annotated full-page screenshot."""

    @pytest.mark.asyncio
    async def test_requires_refs(self, engine):
        """No refs cached -> clear error telling the user to run snapshot -i."""
        engine._ref_map = {}
        with pytest.raises(RuntimeError, match="no refs cached"):
            await engine.screenshot_annotated()

    @pytest.mark.asyncio
    async def test_scrolls_to_origin_and_restores(self, tmp_path, engine):
        """Scroll must be reset to (0,0) for capture and restored afterwards."""
        from unittest.mock import call
        engine._ref_map = {
            "@e0": {"frame_index": 0, "tag": "button", "text": "Click"},
        }
        # Mock a locator with a bounding_box
        mock_locator = AsyncMock()
        mock_locator.bounding_box = AsyncMock(return_value={
            "x": 10.0, "y": 20.0, "width": 100.0, "height": 40.0,
        })
        engine.page.locator = MagicMock(return_value=mock_locator)

        # Scroll evaluate returns [50, 200] first, then None for scrollTo calls
        evaluate_mock = AsyncMock(side_effect=[[50, 200], None, None])
        engine.page.evaluate = evaluate_mock
        engine.page.wait_for_timeout = AsyncMock()
        # Minimal 2x2 transparent PNG bytes
        import io
        from PIL import Image as _Image
        buf = io.BytesIO()
        _Image.new("RGBA", (1280, 720), (255, 255, 255, 255)).save(buf, "PNG")
        engine.page.screenshot = AsyncMock(return_value=buf.getvalue())
        engine.page.viewport_size = {"width": 1280, "height": 720}

        out_path = str(tmp_path / "annot.png")
        result = await engine.screenshot_annotated(out_path)

        # Legend has our one box
        assert result["path"] == out_path
        assert len(result["legend"]) == 1
        assert result["legend"][0]["ref"] == "@e0"
        assert result["legend"][0]["tag"] == "button"

        # Output file exists and is non-empty
        from pathlib import Path as _P
        assert _P(out_path).stat().st_size > 0

        # Called: read-scroll, scrollTo(0,0) instant, scrollTo restore instant
        calls = evaluate_mock.call_args_list
        assert calls[0].args[0] == "[window.scrollX, window.scrollY]"
        assert "scrollTo" in calls[1].args[0] and "behavior: 'instant'" in calls[1].args[0]
        assert "0" in calls[1].args[0]  # scrolling to origin
        # Restore call passes saved coords as second arg
        assert "scrollTo" in calls[2].args[0] and "behavior: 'instant'" in calls[2].args[0]
        assert calls[2].args[1] == [50, 200]

    @pytest.mark.asyncio
    async def test_restores_scroll_even_on_failure(self, engine):
        """If screenshot fails, the original scroll must still be restored."""
        engine._ref_map = {"@e0": {"frame_index": 0, "tag": "a", "text": "x"}}
        evaluate_mock = AsyncMock(side_effect=[[100, 200], None, None])
        engine.page.evaluate = evaluate_mock
        engine.page.wait_for_timeout = AsyncMock()
        engine.page.screenshot = AsyncMock(side_effect=Exception("boom"))
        engine.page.viewport_size = {"width": 1280, "height": 720}

        with pytest.raises(Exception, match="boom"):
            await engine.screenshot_annotated()

        # Last call must be the restore-scroll, passing saved coords as arg
        last = evaluate_mock.call_args_list[-1]
        assert "scrollTo" in last.args[0] and "behavior: 'instant'" in last.args[0]
        assert last.args[1] == [100, 200]

    @pytest.mark.asyncio
    async def test_skips_refs_with_no_bounding_box(self, tmp_path, engine):
        """Hidden elements return None from bounding_box() -- skip them."""
        engine._ref_map = {
            "@e0": {"frame_index": 0, "tag": "button", "text": "Visible"},
            "@e1": {"frame_index": 0, "tag": "input", "text": ""},
        }
        visible_loc = AsyncMock()
        visible_loc.bounding_box = AsyncMock(return_value={
            "x": 0.0, "y": 0.0, "width": 50.0, "height": 20.0,
        })
        hidden_loc = AsyncMock()
        hidden_loc.bounding_box = AsyncMock(return_value=None)

        def _locator_for(sel):
            # @e0 -> visible, @e1 -> hidden
            if '@e0' in sel:
                return visible_loc
            return hidden_loc

        engine.page.locator = MagicMock(side_effect=_locator_for)
        engine.page.evaluate = AsyncMock(side_effect=[[0, 0], None, None])
        engine.page.wait_for_timeout = AsyncMock()
        import io
        from PIL import Image as _Image
        buf = io.BytesIO()
        _Image.new("RGBA", (1280, 720), (255, 255, 255, 255)).save(buf, "PNG")
        engine.page.screenshot = AsyncMock(return_value=buf.getvalue())
        engine.page.viewport_size = {"width": 1280, "height": 720}

        result = await engine.screenshot_annotated(str(tmp_path / "x.png"))
        # Only the visible one ends up in the legend
        assert len(result["legend"]) == 1
        assert result["legend"][0]["ref"] == "@e0"


class TestNavigation:
    """F9: back, forward, reload."""

    @pytest.mark.asyncio
    async def test_go_back(self, engine):
        engine.page.go_back = AsyncMock()
        engine.page.url = "https://example.com/previous"
        engine.page.title = AsyncMock(return_value="Previous Page")
        result = await engine.go_back()
        assert result["url"] == "https://example.com/previous"
        engine.page.go_back.assert_called_once()

    @pytest.mark.asyncio
    async def test_go_forward(self, engine):
        engine.page.go_forward = AsyncMock()
        engine.page.url = "https://example.com/next"
        engine.page.title = AsyncMock(return_value="Next Page")
        result = await engine.go_forward()
        assert result["url"] == "https://example.com/next"

    @pytest.mark.asyncio
    async def test_reload(self, engine):
        engine.page.reload = AsyncMock()
        engine.page.url = "https://example.com/"
        engine.page.title = AsyncMock(return_value="Reloaded")
        result = await engine.reload()
        assert result["title"] == "Reloaded"

    @pytest.mark.asyncio
    async def test_navigation_clears_refs(self, engine):
        engine._ref_map = {"@e0": {"frame_index": 0, "tag": "a", "text": "link"}}
        engine.page.go_back = AsyncMock()
        engine.page.title = AsyncMock(return_value="Back")
        await engine.go_back()
        assert engine._ref_map == {}


class TestSnapshotRefs:
    """F6: Snapshot refs with data-ref injection."""

    @pytest.mark.asyncio
    async def test_snapshot_interactive_injects_refs(self, engine):
        engine.page.evaluate = AsyncMock(return_value=[
            {"ref": "@e0", "tag": "button", "text": "Submit", "desc": "@e0 <button> Submit"},
            {"ref": "@e1", "tag": "input", "text": "", "desc": '@e1 <input type="text">'},
        ])
        engine.page.frames = [engine.page]  # Only main frame

        result = await engine.snapshot(interactive=True)
        assert "@e0" in result
        assert "@e1" in result
        assert "Interactive elements (2):" in result
        assert engine._ref_map["@e0"]["tag"] == "button"
        assert engine._ref_map["@e1"]["tag"] == "input"

    @pytest.mark.asyncio
    async def test_snapshot_clears_old_refs(self, engine):
        engine._ref_map = {"@e99": {"frame_index": 0, "tag": "div", "text": "old"}}
        engine.page.evaluate = AsyncMock(return_value=[])
        engine.page.frames = [engine.page]

        await engine.snapshot(interactive=True)
        assert "@e99" not in engine._ref_map

    def test_resolve_ref_success(self, engine):
        engine._ref_map = {"@e0": {"frame_index": 0, "tag": "button", "text": "ok"}}
        css, fi = engine._resolve_selector("@e0")
        assert css == '[data-ref="@e0"]'
        assert fi == 0

    def test_resolve_ref_not_found(self, engine):
        with pytest.raises(ValueError, match="ref @e99 not found"):
            engine._resolve_selector("@e99")

    def test_resolve_css_selector(self, engine):
        css, fi = engine._resolve_selector("#my-button")
        assert css == "#my-button"
        assert fi == 0

    @pytest.mark.asyncio
    async def test_click_with_ref(self, engine):
        engine._ref_map = {"@e0": {"frame_index": 0, "tag": "button", "text": "ok"}}
        result = await engine.click("@e0")
        engine.behavior.click.assert_called_once_with('[data-ref="@e0"]')
        assert "clicked @e0" in result

    @pytest.mark.asyncio
    async def test_click_ref_multi_match_raises(self, engine):
        """Ref selector matches multiple DOM elements → clear error, not Playwright strict crash."""
        engine._ref_map = {"@e0": {"frame_index": 0, "tag": "button", "text": "ok"}}

        # Mock page.query_selector_all to return 2 elements
        engine.page.query_selector_all = AsyncMock(
            return_value=[MagicMock(), MagicMock()]
        )
        with pytest.raises(ValueError, match="matched 2 elements"):
            await engine.click("@e0")

    @pytest.mark.asyncio
    async def test_fill_ref_multi_match_raises(self, engine):
        """fill with duplicate ref → same clear error."""
        engine._ref_map = {"@e0": {"frame_index": 0, "tag": "input", "text": ""}}
        engine.page.query_selector_all = AsyncMock(
            return_value=[MagicMock(), MagicMock()]
        )
        with pytest.raises(ValueError, match="matched 2 elements"):
            await engine.fill("@e0", "text")


class TestIframeRefs:
    """F12: iframe ref injection."""

    @pytest.mark.asyncio
    async def test_snapshot_with_iframe(self, engine):
        # Main frame returns one element
        mock_main_eval = AsyncMock(return_value=[
            {"ref": "@e0", "tag": "button", "text": "Main", "desc": "@e0 <button> Main"},
        ])

        # iframe returns one element
        mock_iframe = MagicMock()
        mock_iframe.name = "my-iframe"
        mock_iframe.url = "https://example.com/iframe"
        mock_iframe_eval = AsyncMock(return_value=[
            {"ref": "@e1", "tag": "a", "text": "Link", "desc": "@e1 <a> Link"},
        ])
        mock_iframe.evaluate = mock_iframe_eval

        engine.page.evaluate = mock_main_eval
        engine.page.frames = [engine.page, mock_iframe]

        result = await engine.snapshot(interactive=True)
        assert "@e0" in result
        assert "@e1" in result
        assert "[iframe: my-iframe]" in result
        assert engine._ref_map["@e0"]["frame_index"] == 0
        assert engine._ref_map["@e1"]["frame_index"] == 1

    @pytest.mark.asyncio
    async def test_snapshot_cross_origin_iframe(self, engine):
        mock_iframe = MagicMock()
        mock_iframe.name = "cross-frame"
        mock_iframe.url = "https://other.com/frame"
        mock_iframe.evaluate = AsyncMock(side_effect=Exception("cross-origin"))

        engine.page.evaluate = AsyncMock(return_value=[])
        engine.page.frames = [engine.page, mock_iframe]

        result = await engine.snapshot(interactive=True)
        assert "[cross-origin]" in result


class TestSelectCheck:
    """F10: select, check, uncheck."""

    @pytest.mark.asyncio
    async def test_select_option(self, engine):
        locator = AsyncMock()
        engine.page.locator = MagicMock(return_value=locator)
        result = await engine.select_option("#dropdown", "value1")
        locator.hover.assert_called_once()
        locator.select_option.assert_called_once_with("value1")
        assert "selected" in result

    @pytest.mark.asyncio
    async def test_check(self, engine):
        locator = AsyncMock()
        engine.page.locator = MagicMock(return_value=locator)
        result = await engine.check("#checkbox")
        locator.hover.assert_called_once()
        locator.check.assert_called_once()
        assert "checked" in result

    @pytest.mark.asyncio
    async def test_uncheck(self, engine):
        locator = AsyncMock()
        engine.page.locator = MagicMock(return_value=locator)
        result = await engine.uncheck("#checkbox")
        locator.hover.assert_called_once()
        locator.uncheck.assert_called_once()
        assert "unchecked" in result


class TestWait:
    """F7: wait commands."""

    @pytest.mark.asyncio
    async def test_wait_for_element(self, engine):
        locator = AsyncMock()
        engine.page.locator = MagicMock(return_value=locator)
        result = await engine.wait_for_element("#el")
        locator.wait_for.assert_called_once_with(state="visible", timeout=30000)
        assert "visible" in result

    @pytest.mark.asyncio
    async def test_wait_for_text(self, engine):
        locator = AsyncMock()
        engine.page.get_by_text = MagicMock(return_value=locator)
        result = await engine.wait_for_text("Hello")
        locator.wait_for.assert_called_once()
        assert "Hello" in result

    @pytest.mark.asyncio
    async def test_wait_for_network_idle(self, engine):
        engine.page.wait_for_load_state = AsyncMock()
        result = await engine.wait_for_network_idle()
        engine.page.wait_for_load_state.assert_called_once_with(
            "networkidle", timeout=30000
        )
        assert "idle" in result

    @pytest.mark.asyncio
    async def test_wait_for_timeout(self, engine):
        engine.page.wait_for_timeout = AsyncMock()
        result = await engine.wait_for_timeout(1000)
        engine.page.wait_for_timeout.assert_called_once_with(1000)
        assert "1000ms" in result


class TestDialog:
    """F8: dialog handling."""

    @pytest.mark.asyncio
    async def test_dialog_accept(self, engine):
        mock_dialog = AsyncMock()
        mock_dialog.type = "alert"
        mock_dialog.message = "Are you sure?"
        engine._pending_dialog = mock_dialog

        result = await engine.dialog_accept()
        mock_dialog.accept.assert_called_once()
        assert "accepted" in result
        assert engine._pending_dialog is None

    @pytest.mark.asyncio
    async def test_dialog_accept_with_text(self, engine):
        mock_dialog = AsyncMock()
        engine._pending_dialog = mock_dialog

        await engine.dialog_accept("my input")
        mock_dialog.accept.assert_called_once_with("my input")
        assert engine._pending_dialog is None

    @pytest.mark.asyncio
    async def test_dialog_dismiss(self, engine):
        mock_dialog = AsyncMock()
        engine._pending_dialog = mock_dialog

        result = await engine.dialog_dismiss()
        mock_dialog.dismiss.assert_called_once()
        assert "dismissed" in result
        assert engine._pending_dialog is None

    def test_dialog_info_no_dialog(self, engine):
        result = engine.dialog_info()
        assert result["present"] is False

    def test_dialog_info_with_pending(self, engine):
        mock_dialog = MagicMock()
        mock_dialog.type = "confirm"
        mock_dialog.message = "OK?"
        mock_dialog.default_value = ""
        engine._pending_dialog = mock_dialog

        result = engine.dialog_info()
        assert result["present"] is True
        assert result["type"] == "confirm"
        assert result["handled"] is False

    def test_dialog_info_with_handled(self, engine):
        mock_dialog = MagicMock()
        mock_dialog.type = "alert"
        mock_dialog.message = "Done"
        mock_dialog.default_value = ""
        engine._last_dialog = mock_dialog
        engine._dialog_handled = True
        engine._pending_dialog = None

        result = engine.dialog_info()
        assert result["present"] is True
        assert result["handled"] is True

    @pytest.mark.asyncio
    async def test_dialog_no_dialog_present(self, engine):
        engine._pending_dialog = None
        result = await engine.dialog_accept()
        assert "no dialog" in result

    def test_set_auto_dismiss(self, engine):
        result = engine.set_auto_dismiss(True)
        assert engine._auto_dismiss_dialogs is True
        assert "on" in result
        result = engine.set_auto_dismiss(False)
        assert engine._auto_dismiss_dialogs is False
        assert "off" in result


class TestMultiTab:
    """F11: multi-tab management."""

    @pytest.mark.asyncio
    async def test_tab_create(self, engine):
        new_page = AsyncMock()
        new_page.url = "about:blank"
        new_page.on = MagicMock()
        engine.context.new_page = AsyncMock(return_value=new_page)

        result = await engine.tab_create()
        assert "tab_id" in result
        assert result["tab_id"] == 2  # Second tab (IDs start at 1)
        assert engine._active_tab_id == 2

    @pytest.mark.asyncio
    async def test_tab_create_with_url(self, engine):
        new_page = AsyncMock()
        new_page.url = "https://example.com/"
        new_page.title = AsyncMock(return_value="Example")
        new_page.on = MagicMock()
        new_page.goto = AsyncMock()
        engine.context.new_page = AsyncMock(return_value=new_page)

        result = await engine.tab_create("https://example.com/")
        assert result["url"] == "https://example.com/"
        assert result["title"] == "Example"

    @pytest.mark.asyncio
    async def test_tab_close(self, engine):
        # Add a second tab
        new_page = AsyncMock()
        new_page.url = "https://other.com/"
        new_page.on = MagicMock()
        engine.context = AsyncMock()
        engine.context.new_page = AsyncMock(return_value=new_page)
        await engine.tab_create()

        # Now close tab 2 (the active one)
        result = await engine.tab_close(2)
        assert "closed" in result
        assert 2 not in engine._tabs
        assert engine._active_tab_id == 1  # Falls back to tab 1

    @pytest.mark.asyncio
    async def test_tab_close_not_found(self, engine):
        with pytest.raises(ValueError, match="tab 99 not found"):
            await engine.tab_close(99)

    def test_tab_switch(self, engine):
        # Add a second tab manually
        mock_page2 = MagicMock()
        mock_tab2 = MagicMock(spec=TabInfo)
        mock_tab2.page = mock_page2
        engine._tabs[2] = mock_tab2
        engine._next_tab_id = 3

        result = engine.tab_switch(2)
        assert engine._active_tab_id == 2
        assert "switched" in result

    def test_tab_switch_not_found(self, engine):
        with pytest.raises(ValueError, match="tab 5 not found"):
            engine.tab_switch(5)

    @pytest.mark.asyncio
    async def test_tab_list(self, engine):
        tabs = await engine.tab_list()
        assert len(tabs) == 1
        assert tabs[0]["tab_id"] == 1
        assert tabs[0]["active"] is True
        assert "title" in tabs[0]

    @pytest.mark.asyncio
    async def test_tab_list_multiple(self, engine):
        mock_page2 = AsyncMock()
        mock_page2.url = "https://other.com/"
        mock_page2.title = AsyncMock(return_value="Other")
        mock_tab2 = MagicMock(spec=TabInfo)
        mock_tab2.page = mock_page2
        engine._tabs[2] = mock_tab2

        tabs = await engine.tab_list()
        assert len(tabs) == 2

    def test_page_raises_when_no_tabs(self, engine):
        """After closing all tabs, page property raises RuntimeError."""
        engine._tabs.clear()
        engine.browser = MagicMock()  # browser still alive
        with pytest.raises(RuntimeError, match="no active tab"):
            _ = engine.page

    @pytest.mark.asyncio
    async def test_tab_create_clears_refs(self, engine):
        engine._ref_map = {"@e0": {"frame_index": 0, "tag": "a", "text": "x"}}
        new_page = AsyncMock()
        new_page.url = "about:blank"
        new_page.on = MagicMock()
        engine.context.new_page = AsyncMock(return_value=new_page)
        await engine.tab_create()
        assert engine._ref_map == {}
