"""Unit tests for stealth_browser.behavior."""

from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import pytest
from stealth_browser.behavior import HumanBehavior


@pytest.fixture
def mock_page():
    """Create a mock Patchright page."""
    page = AsyncMock()
    page.keyboard = AsyncMock()
    page.mouse = AsyncMock()
    page.locator = MagicMock(return_value=AsyncMock())
    return page


@pytest.fixture
def behavior(mock_page):
    """Create a HumanBehavior with mocked Humanization."""
    with patch("stealth_browser.behavior.Humanization") as MockH:
        instance = MagicMock()
        instance.move_to = AsyncMock(return_value=(100.0, 200.0))
        instance.click_at = AsyncMock()
        instance.generate_bezier_points = MagicMock(
            return_value=[(i, 100) for i in range(0, 280, 5)]
        )
        instance.config = MagicMock()
        instance.config.humanize = True
        MockH.return_value = instance
        hb = HumanBehavior(mock_page, fast=False)
        yield hb


class TestClick:
    @pytest.mark.asyncio
    async def test_click_calls_move_and_click(self, behavior, mock_page):
        await behavior.click("#button")
        behavior._h.move_to.assert_called_once()
        behavior._h.click_at.assert_called_once()


class TestFill:
    @pytest.mark.asyncio
    async def test_fill_types_all_characters(self, behavior, mock_page):
        await behavior.fill("#input", "abc")
        # Should have at least 3 keyboard.press calls (one per char)
        # May have more due to typo simulation
        calls = mock_page.keyboard.press.call_args_list
        # At minimum, the 3 correct chars were typed
        typed_chars = [c.args[0] for c in calls]
        assert "a" in typed_chars
        assert "b" in typed_chars
        assert "c" in typed_chars

    @pytest.mark.asyncio
    async def test_fill_clicks_first(self, behavior, mock_page):
        await behavior.fill("#input", "x")
        behavior._h.click_at.assert_called_once()

    @pytest.mark.asyncio
    async def test_fill_clears_before_typing(self, behavior, mock_page):
        """fill() must select-all + delete existing content before typing."""
        await behavior.fill("#input", "new")
        calls = mock_page.keyboard.press.call_args_list
        keys = [c.args[0] for c in calls]
        # Must see Meta+a (select all) followed by Backspace/Delete before any content chars
        assert "Meta+a" in keys
        meta_a_idx = keys.index("Meta+a")
        delete_idx = next(
            i for i, k in enumerate(keys)
            if k in ("Backspace", "Delete") and i > meta_a_idx
        )
        # First content char must come after delete
        first_content = next(
            i for i, k in enumerate(keys)
            if k in ("n", "e", "w") and i > delete_idx
        )
        assert first_content > delete_idx

    @pytest.mark.asyncio
    async def test_fill_empty_string_clears(self, behavior, mock_page):
        """fill(selector, '') must clear the input (select-all + delete)."""
        await behavior.fill("#input", "")
        calls = mock_page.keyboard.press.call_args_list
        keys = [c.args[0] for c in calls]
        assert "Meta+a" in keys
        assert any(k in ("Backspace", "Delete") for k in keys)


class TestTypeText:
    @pytest.mark.asyncio
    async def test_type_text_presses_keys(self, behavior, mock_page):
        await behavior.type_text("hi")
        calls = mock_page.keyboard.press.call_args_list
        typed = [c.args[0] for c in calls]
        assert "h" in typed
        assert "i" in typed


class TestScroll:
    @pytest.mark.asyncio
    async def test_scroll_down(self, behavior, mock_page):
        await behavior.scroll("down", 2)
        # Should have called mouse.wheel multiple times
        assert mock_page.mouse.wheel.call_count > 0

    @pytest.mark.asyncio
    async def test_scroll_up(self, behavior, mock_page):
        await behavior.scroll("up", 1)
        assert mock_page.mouse.wheel.call_count > 0


class TestDrag:
    @pytest.mark.asyncio
    async def test_drag_sequence(self, behavior, mock_page):
        await behavior.drag(10, 100, 290, 100, steps=20)
        # Should follow: move -> down -> multiple moves -> up
        mock_page.mouse.down.assert_called_once()
        mock_page.mouse.up.assert_called_once()
        assert mock_page.mouse.move.call_count > 1
