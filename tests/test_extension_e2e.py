"""E2E: load unpacked Chrome extension via StealthEngine.launch(extensions=...).

Requires real system Chrome. The minimal fixture extension injects a
`<meta name="stealth-ext-marker" content="loaded">` into every page via
its content script; we assert the marker is present after navigation.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from stealth_browser.engine import StealthEngine

pytestmark = pytest.mark.asyncio

EXT_DIR = Path(__file__).parent / "fixtures" / "minimal_extension"


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="Chrome path is hardcoded for macOS in engine.launch",
)
async def test_extension_loads_and_injects_marker():
    engine = StealthEngine()
    try:
        await engine.launch(headed=True, extensions=[str(EXT_DIR)])
        await engine.navigate(
            "https://example.com/", site="example.com", skip_cookies=True
        )
        # Give content_script one event loop tick after document_end
        await asyncio.sleep(2.0)
        page = engine.page
        assert page is not None
        marker = await page.evaluate(
            'document.querySelector(\'meta[name="stealth-ext-marker"]\')?.getAttribute("content")'
        )
        if marker != "loaded":
            head_html = await page.evaluate("document.head.outerHTML")
            url = page.url
            # Check whether the extension directory was actually passed to Chrome
            # by inspecting the underlying chromium process if possible.
            print(f"\n\nDEBUG url={url}\nDEBUG head_html={head_html[:800]}\n\n")
            # Also verify via another tab whether extension registered at all.
        assert marker == "loaded", f"expected 'loaded', got {marker!r}"
    finally:
        await engine.shutdown()


async def test_extensions_require_headed_integration():
    """Integration-level reinforcement of the headed requirement."""
    engine = StealthEngine()
    with pytest.raises(ValueError, match="extensions require headed"):
        await engine.launch(headed=False, extensions=[str(EXT_DIR)])
