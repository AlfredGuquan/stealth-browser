"""Patchright browser engine -- launch, context, page management.

Key constraints (tracer-verified):
- Must use channel='chrome' (system Chrome), not bundled Chromium
- Headless UA still contains "HeadlessChrome" -- must override in new_context()
- Must use patchright.async_api for daemon architecture (sync API greenlet issue)
- Cookie injection: after new_context(), before first goto()

V2 additions:
- Multi-tab: self.pages dict, active_tab_id, per-tab HumanBehavior/CaptchaSolver
- Snapshot refs: data-ref injection, ref_map, resolve_selector()
- iframe support: cross-frame ref injection with global counter
- Wait, dialog, navigation, select/check commands
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

from patchright.async_api import Browser, BrowserContext, Dialog, Page, Playwright
from patchright.async_api import TimeoutError as PlaywrightTimeoutError
from patchright.async_api import async_playwright

from .behavior import HumanBehavior
from .captcha import CaptchaSolver
from .cookies import clear_cache, get_cookies_for_site
from .utils import get_chrome_ua, is_login_redirect, warn

logger = logging.getLogger("stealth_browser.engine")

# Ref pattern: @e0, @e1, @e42, etc.
REF_PATTERN = re.compile(r"^@e\d+$")


class TabInfo:
    """Per-tab state: page + behavior + captcha instances."""

    __slots__ = ("page", "behavior", "captcha")

    def __init__(self, page: Page, *, fast: bool = False):
        self.page = page
        self.behavior = HumanBehavior(page, fast=fast)
        self.captcha = CaptchaSolver(page, self.behavior)


class StealthEngine:
    """Manages a Patchright browser instance with anti-detection configuration.

    Provides the async API used by the daemon to handle CLI commands.

    V2: Multi-tab architecture. Each tab gets its own HumanBehavior and
    CaptchaSolver instances (they cache page state internally).
    """

    def __init__(self) -> None:
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None

        # Multi-tab state (F11)
        self._tabs: dict[int, TabInfo] = {}
        self._active_tab_id: int = 0
        self._next_tab_id: int = 1  # PRD: tab IDs start at 1

        # Snapshot refs state (F6/F12)
        self._ref_map: dict[str, dict[str, Any]] = {}
        # Maps ref -> {frame_index: int, tag: str, text: str}

        # Dialog state (F8)
        self._pending_dialog: Dialog | None = None
        self._last_dialog: Dialog | None = None
        self._dialog_handled: bool = True
        self._auto_dismiss_dialogs: bool = False  # Default off: let user handle dialogs

        self._current_site: str | None = None
        self._headed: bool = False

        # Network recording state
        self._network_log: list[dict[str, Any]] = []
        self._network_mark: int | None = None  # index into _network_log when start was called
        self._network_max: int = 5000  # ring buffer cap

    # -- V1 compat properties --

    @property
    def page(self) -> Page | None:
        if not self._tabs:
            if self.browser is not None:
                raise RuntimeError("no active tab -- create one with 'tab create'")
            return None
        tab = self._tabs.get(self._active_tab_id)
        return tab.page if tab else None

    @property
    def behavior(self) -> HumanBehavior | None:
        tab = self._tabs.get(self._active_tab_id)
        return tab.behavior if tab else None

    @property
    def captcha(self) -> CaptchaSolver | None:
        tab = self._tabs.get(self._active_tab_id)
        return tab.captcha if tab else None

    # -- Lifecycle --

    async def launch(self, *, headed: bool = False) -> None:
        """Launch the browser with anti-detection configuration."""
        self._headed = headed
        self.playwright = await async_playwright().start()

        chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if not os.path.exists(chrome_path):
            raise RuntimeError(
                "Google Chrome not found at expected path. "
                "Install Chrome from https://www.google.com/chrome/"
            )

        self.browser = await self.playwright.chromium.launch(
            headless=not headed,
            channel="chrome",
        )

        self.context = await self.browser.new_context(
            user_agent=get_chrome_ua(),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )

        # Create initial tab
        page = await self.context.new_page()
        self._register_tab(page)
        self._setup_dialog_handler(page)
        self._setup_network_handler(page)
        logger.info("browser launched (headed=%s)", headed)

    def _register_tab(self, page: Page) -> int:
        """Register a new page as a tab. Returns its tab_id."""
        tab_id = self._next_tab_id
        self._next_tab_id += 1
        self._tabs[tab_id] = TabInfo(page, fast=False)
        self._active_tab_id = tab_id
        return tab_id

    def _setup_dialog_handler(self, page: Page) -> None:
        """Attach dialog handler to a page (F8).

        When auto-dismiss is off (default), the dialog is stored in
        _pending_dialog for explicit accept/dismiss via CLI.
        When auto-dismiss is on, the dialog is dismissed immediately
        and only logged.
        """
        async def _on_dialog(dialog: Dialog) -> None:
            self._last_dialog = dialog
            if self._auto_dismiss_dialogs:
                await dialog.dismiss()
                self._dialog_handled = True
                self._pending_dialog = None
                logger.info("auto-dismissed %s dialog: %s", dialog.type, dialog.message)
            else:
                self._pending_dialog = dialog
                self._dialog_handled = False

        page.on("dialog", _on_dialog)

    def _setup_network_handler(self, page: Page) -> None:
        """Attach request/response listeners for always-on network recording."""
        import time as _time

        def _on_request(request) -> None:
            entry = {
                "url": request.url,
                "method": request.method,
                "resource_type": request.resource_type,
                "post_data": request.post_data[:2000] if request.post_data else None,
                "timestamp": _time.time(),
                "status": None,
                "content_type": None,
                "response_size": None,
            }
            # Enforce ring buffer cap
            if len(self._network_log) >= self._network_max:
                # Shift mark if it exists and we're trimming
                if self._network_mark is not None:
                    if self._network_mark > 0:
                        self._network_mark -= 1
                    else:
                        self._network_mark = 0
                self._network_log.pop(0)
            self._network_log.append(entry)

        def _on_response(response) -> None:
            url = response.url
            # Walk backwards to find the matching request entry
            for entry in reversed(self._network_log):
                if entry["url"] == url and entry["status"] is None:
                    entry["status"] = response.status
                    headers = response.headers
                    entry["content_type"] = headers.get("content-type", "")
                    cl = headers.get("content-length")
                    if cl and cl.isdigit():
                        entry["response_size"] = int(cl)
                    break

        page.on("request", _on_request)
        page.on("response", _on_response)

    # -- Network recording --

    def network_start(self) -> str:
        """Mark the current position in the network log."""
        self._network_mark = len(self._network_log)
        return "recording started"

    def network_stop(
        self,
        types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return requests captured since start, then clear mark."""
        if self._network_mark is None:
            return {"entries": [], "note": "no recording in progress (call network start first)"}
        entries = self._network_log[self._network_mark:]
        self._network_mark = None
        filtered = self._filter_network(entries, types)
        return {"entries": filtered, "total": len(entries), "shown": len(filtered)}

    def network_list(
        self,
        types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return all buffered requests."""
        filtered = self._filter_network(self._network_log, types)
        return {"entries": filtered, "total": len(self._network_log), "shown": len(filtered)}

    def network_clear(self) -> str:
        """Clear the network log and mark."""
        self._network_log.clear()
        self._network_mark = None
        return "network log cleared"

    @staticmethod
    def _filter_network(
        entries: list[dict[str, Any]],
        types: list[str] | None,
    ) -> list[dict[str, Any]]:
        """Filter entries by resource type. None means no filter (return all)."""
        if not types:
            return entries
        return [e for e in entries if e.get("resource_type") in types]

    async def shutdown(self) -> None:
        """Close browser and clean up."""
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
        self._tabs.clear()
        self.context = None
        self._ref_map.clear()
        logger.info("browser shut down")

    @property
    def is_alive(self) -> bool:
        return self.browser is not None and self.browser.is_connected()

    # -- Cookie --

    async def inject_cookies(self, site: str, url: str) -> int:
        """Extract/load cookies for a site and inject into the browser context."""
        if self.context is None:
            raise RuntimeError("browser not launched")
        cookies = get_cookies_for_site(site, url)
        if not cookies:
            return 0
        await self.context.add_cookies(cookies)
        self._current_site = site
        return len(cookies)

    # -- Navigation (F9 extends) --

    async def navigate(
        self,
        url: str,
        *,
        site: str | None = None,
        timeout: int = 30000,
        skip_cookies: bool = False,
    ) -> dict[str, Any]:
        """Navigate to a URL. If site is given, inject cookies first.

        When skip_cookies=True (F14: localhost / --no-cookie), both cookie
        injection and login_redirect detection are bypassed. This prevents
        the "session expired" warning from firing on dev URLs that happen
        to use /login paths.
        """
        if self.page is None:
            raise RuntimeError("browser not launched")

        if not skip_cookies and site and self._current_site != site:
            count = await self.inject_cookies(site, url)
            logger.info("injected %d cookies for %s", count, site)

        await self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        await self.page.wait_for_timeout(2000)

        # Navigation invalidates refs
        self._clear_refs()

        final_url = self.page.url
        title = await self.page.title()

        if not skip_cookies and is_login_redirect(final_url) and site:
            logger.info("login redirect detected, re-extracting cookies")
            clear_cache(site)
            count = await self.inject_cookies(site, url)
            if count > 0:
                await self.page.goto(
                    url, wait_until="domcontentloaded", timeout=timeout
                )
                await self.page.wait_for_timeout(2000)
                final_url = self.page.url
                title = await self.page.title()

                if is_login_redirect(final_url):
                    warn(
                        f"session expired for {site}. "
                        f"Please log in to {site} in Chrome and retry."
                    )
                    return {
                        "url": final_url,
                        "title": title,
                        "login_redirect": True,
                    }
            else:
                warn(
                    f"no cookies extracted for {site}. "
                    f"Please log in to {site} in Chrome."
                )
                return {
                    "url": final_url,
                    "title": title,
                    "login_redirect": True,
                }

        return {
            "url": final_url,
            "title": title,
            "login_redirect": False,
        }

    async def go_back(self) -> dict[str, Any]:
        """Navigate back (F9)."""
        if self.page is None:
            raise RuntimeError("browser not launched")
        await self.page.go_back(wait_until="commit")
        await self.page.wait_for_timeout(1000)
        self._clear_refs()
        return {"url": self.page.url, "title": await self.page.title()}

    async def go_forward(self) -> dict[str, Any]:
        """Navigate forward (F9)."""
        if self.page is None:
            raise RuntimeError("browser not launched")
        await self.page.go_forward(wait_until="commit")
        await self.page.wait_for_timeout(1000)
        self._clear_refs()
        return {"url": self.page.url, "title": await self.page.title()}

    async def reload(self) -> dict[str, Any]:
        """Reload current page (F9)."""
        if self.page is None:
            raise RuntimeError("browser not launched")
        await self.page.reload(wait_until="domcontentloaded")
        self._clear_refs()
        return {"url": self.page.url, "title": await self.page.title()}

    # -- Snapshot with refs (F6/F12) --

    def _clear_refs(self) -> None:
        """Clear the ref map (after navigation or new snapshot)."""
        self._ref_map.clear()

    def _resolve_selector(self, selector: str) -> tuple[str, int]:
        """Resolve a selector that may be a ref (@eN) or CSS selector.

        Returns (css_selector, frame_index).
        """
        if REF_PATTERN.match(selector):
            ref_info = self._ref_map.get(selector)
            if ref_info is None:
                raise ValueError(
                    f"ref {selector} not found. "
                    "Run 'snapshot -i' to refresh refs."
                )
            return f'[data-ref="{selector}"]', ref_info["frame_index"]
        return selector, 0  # CSS selector, main frame

    async def _get_locator(self, selector: str, *, _resolved: tuple[str, int] | None = None):
        """Get a Playwright locator for a selector (ref or CSS), handling iframes.

        If _resolved is provided, skip resolve_selector (avoids double resolve).
        """
        if self.page is None:
            raise RuntimeError("browser not launched")

        css, frame_index = _resolved if _resolved else self._resolve_selector(selector)

        if frame_index == 0:
            return self.page.locator(css)

        # iframe locator: find the frame by index
        frames = self.page.frames
        if frame_index < len(frames):
            frame = frames[frame_index]
            # Use frame.locator for same-origin frames
            return frame.locator(css)

        raise ValueError(
            f"frame index {frame_index} out of range "
            f"(page has {len(frames)} frames)"
        )

    async def snapshot(self, *, interactive: bool = False) -> str:
        """Return a text snapshot of the page.

        If interactive=True, injects data-ref attributes and returns
        elements with @eN refs (F6). Traverses iframes (F12).
        """
        if self.page is None:
            raise RuntimeError("browser not launched")

        url = self.page.url
        title = await self.page.title()
        lines = [f"URL: {url}", f"Title: {title}", ""]

        if interactive:
            # Clear old refs before injecting new ones
            self._clear_refs()

            # Inject refs into main frame and collect elements
            all_elements = []
            ref_counter = 0

            # Main frame (frame_index=0)
            main_result = await self.page.evaluate("""(startIndex) => {
                const selectors = 'a, button, input, select, textarea, [role="button"], [role="checkbox"], [role="radio"], [onclick]';
                const els = document.querySelectorAll(selectors);
                return Array.from(els).map((el, i) => {
                    const ref = '@e' + (startIndex + i);
                    el.setAttribute('data-ref', ref);
                    const tag = el.tagName.toLowerCase();
                    const text = el.textContent?.trim().slice(0, 80) || '';
                    const type = el.getAttribute('type') || '';
                    const name = el.getAttribute('name') || '';
                    const href = el.getAttribute('href') || '';
                    const placeholder = el.getAttribute('placeholder') || '';
                    const role = el.getAttribute('role') || '';
                    const value = el.value || '';
                    const ariaLabel = el.getAttribute('aria-label') || '';
                    const checked = el.checked;
                    const tagName = el.tagName;

                    let desc = ref + ' <' + tag;
                    if (type) desc += ' type="' + type + '"';
                    if (name) desc += ' name="' + name + '"';
                    if (role && role !== 'button') desc += ' role="' + role + '"';
                    if (placeholder) desc += ' placeholder="' + placeholder + '"';
                    if (checked) desc += ' checked';
                    desc += '>';
                    if (text && tag !== 'input' && tag !== 'textarea') desc += ' ' + text;
                    if (value && (tag === 'input' || tag === 'textarea')) desc += ' value="' + value.slice(0, 40) + '"';
                    if (href) desc += ' -> ' + href.slice(0, 80);
                    if (ariaLabel) desc += ' [' + ariaLabel + ']';
                    return {ref, tag, text: text.slice(0, 80), desc};
                });
            }""", ref_counter)

            for item in main_result:
                self._ref_map[item["ref"]] = {
                    "frame_index": 0,
                    "tag": item["tag"],
                    "text": item["text"],
                }
                all_elements.append(item["desc"])
            ref_counter += len(main_result)

            # Traverse iframes (F12)
            frames = self.page.frames
            for fi, frame in enumerate(frames):
                if fi == 0:
                    continue  # Skip main frame (already done)

                # Check if cross-origin
                try:
                    frame_result = await frame.evaluate("""(startIndex) => {
                        const selectors = 'a, button, input, select, textarea, [role="button"], [role="checkbox"], [role="radio"], [onclick]';
                        const els = document.querySelectorAll(selectors);
                        return Array.from(els).map((el, i) => {
                            const ref = '@e' + (startIndex + i);
                            el.setAttribute('data-ref', ref);
                            const tag = el.tagName.toLowerCase();
                            const text = el.textContent?.trim().slice(0, 80) || '';
                            const type = el.getAttribute('type') || '';
                            const name = el.getAttribute('name') || '';
                            const href = el.getAttribute('href') || '';
                            const placeholder = el.getAttribute('placeholder') || '';
                            const role = el.getAttribute('role') || '';
                            const value = el.value || '';
                            const ariaLabel = el.getAttribute('aria-label') || '';
                            const checked = el.checked;

                            let desc = ref + ' <' + tag;
                            if (type) desc += ' type="' + type + '"';
                            if (name) desc += ' name="' + name + '"';
                            if (role && role !== 'button') desc += ' role="' + role + '"';
                            if (placeholder) desc += ' placeholder="' + placeholder + '"';
                            if (checked) desc += ' checked';
                            desc += '>';
                            if (text && tag !== 'input' && tag !== 'textarea') desc += ' ' + text;
                            if (value && (tag === 'input' || tag === 'textarea')) desc += ' value="' + value.slice(0, 40) + '"';
                            if (href) desc += ' -> ' + href.slice(0, 80);
                            if (ariaLabel) desc += ' [' + ariaLabel + ']';
                            return {ref, tag, text: text.slice(0, 80), desc};
                        });
                    }""", ref_counter)

                    if frame_result:
                        frame_name = frame.name or frame.url or f"frame-{fi}"
                        all_elements.append(f"  [iframe: {frame_name}]")
                        for item in frame_result:
                            self._ref_map[item["ref"]] = {
                                "frame_index": fi,
                                "tag": item["tag"],
                                "text": item["text"],
                            }
                            all_elements.append(f"  {item['desc']}")
                        ref_counter += len(frame_result)

                except Exception:
                    # Cross-origin iframe -- can't inject refs
                    frame_name = frame.name or frame.url or f"frame-{fi}"
                    all_elements.append(f"  [iframe: {frame_name}] [cross-origin]")

            lines.append(f"Interactive elements ({len(self._ref_map)}):")
            for el in all_elements:
                lines.append(f"  {el}")
        else:
            text = await self.page.evaluate("""() => {
                return document.body?.innerText?.slice(0, 4000) || '';
            }""")
            lines.append(text)

        return "\n".join(lines)

    # -- Interaction commands --

    async def click(self, selector: str) -> str:
        """Click an element with human behavior simulation.

        Accepts @eN refs or CSS selectors.
        """
        if self.behavior is None:
            raise RuntimeError("browser not launched")

        css, frame_index = self._resolve_selector(selector)
        if frame_index == 0:
            await self.behavior.click(css)
        else:
            # For iframe elements, get the locator and click directly
            locator = await self._get_locator(selector)
            await locator.click()
        await self.page.wait_for_timeout(500)
        return f"clicked {selector}"

    async def fill(self, selector: str, text: str) -> str:
        """Fill an input with human-like typing.

        Accepts @eN refs or CSS selectors.
        """
        if self.behavior is None:
            raise RuntimeError("browser not launched")

        css, frame_index = self._resolve_selector(selector)
        if frame_index == 0:
            await self.behavior.fill(css, text)
        else:
            locator = await self._get_locator(selector)
            await locator.fill(text)
        return f"filled {selector} with {len(text)} chars"

    async def type_text(self, text: str) -> str:
        """Type text at the current cursor position."""
        if self.behavior is None:
            raise RuntimeError("browser not launched")
        await self.behavior.type_text(text)
        return f"typed {len(text)} chars"

    async def scroll(self, direction: str, amount: int = 3) -> str:
        """Scroll the page with inertial simulation."""
        if self.behavior is None:
            raise RuntimeError("browser not launched")
        await self.behavior.scroll(direction, amount)
        return f"scrolled {direction} {amount} steps"

    async def upload(self, selector: str, file_path: str) -> str:
        """Upload a file to a file input element."""
        if self.page is None:
            raise RuntimeError("browser not launched")
        locator = await self._get_locator(selector)
        await locator.set_input_files(file_path)
        return f"uploaded {file_path} to {selector}"

    async def screenshot(self, path: str | None = None) -> str:
        """Take a screenshot and return the file path."""
        if self.page is None:
            raise RuntimeError("browser not launched")
        if path is None:
            import tempfile
            f = tempfile.NamedTemporaryFile(
                delete=False, prefix="stealth-", suffix=".png", dir="/tmp"
            )
            path = f.name
            f.close()
        await self.page.screenshot(path=path, full_page=True)
        return path

    async def screenshot_annotated(
        self, path: str | None = None
    ) -> dict[str, Any]:
        """Take a full-page screenshot with @eN refs overlaid (F16).

        Requires a prior `snapshot -i` so ``self._ref_map`` is populated.
        The page is scrolled to (0,0) before capture so that bounding boxes
        (which are viewport-relative) line up with the full-page PNG; the
        original scroll position is restored in a try/finally.

        Iframe-locator bounding boxes are auto-translated to main-page
        coordinates by Playwright, so no manual offset is needed.

        Returns: ``{"path": <file>, "legend": [{ref, tag, text}, ...]}``
        """
        if self.page is None:
            raise RuntimeError("browser not launched")
        if not self._ref_map:
            raise RuntimeError("no refs cached, run snapshot -i first")

        # Save current scroll position so we can restore it after capture.
        # Use behavior:'instant' to bypass any page-level `scroll-behavior:
        # smooth` that would otherwise turn scrollTo into an animation —
        # bounding_box() reads viewport-relative coords, so an in-flight scroll
        # would shift every label by the residual offset.
        saved = await self.page.evaluate("[window.scrollX, window.scrollY]")
        await self.page.evaluate(
            "window.scrollTo({top: 0, left: 0, behavior: 'instant'})"
        )
        try:
            png_bytes = await self.page.screenshot(full_page=True)
            viewport = self.page.viewport_size or {"width": 1920, "height": 1080}
            viewport_w = viewport["width"]

            boxes: list[dict[str, Any]] = []
            for ref, info in self._ref_map.items():
                try:
                    locator = await self._get_locator(ref)
                    bb = await locator.bounding_box()
                except Exception:
                    # hidden / detached / cross-origin iframe -> skip silently
                    continue
                if bb is None:
                    continue
                boxes.append({
                    "ref": ref,
                    "bbox": bb,
                    "tag": info["tag"],
                    "text": info["text"],
                })

            from .annotate import overlay_labels
            out_bytes = overlay_labels(
                png_bytes, boxes, viewport_css_width=viewport_w
            )
        finally:
            await self.page.evaluate(
                "([x, y]) => window.scrollTo({left: x, top: y, behavior: 'instant'})",
                saved,
            )

        if path is None:
            import tempfile
            f = tempfile.NamedTemporaryFile(
                delete=False, prefix="stealth-annot-", suffix=".png", dir="/tmp"
            )
            path = f.name
            f.close()
        Path(path).write_bytes(out_bytes)

        legend = [
            {"ref": b["ref"], "tag": b["tag"], "text": b["text"]}
            for b in boxes
        ]
        return {"path": path, "legend": legend}

    async def eval_js(self, expression: str) -> Any:
        """Evaluate JavaScript on the page and return the result."""
        if self.page is None:
            raise RuntimeError("browser not launched")
        return await self.page.evaluate(expression)

    async def get_info(self, what: str, selector: str | None = None) -> str:
        """Get information from the page."""
        if self.page is None:
            raise RuntimeError("browser not launched")

        if what == "url":
            return self.page.url
        elif what == "title":
            return await self.page.title()
        elif what == "text":
            if selector:
                locator = await self._get_locator(selector)
                return await locator.inner_text()
            else:
                return await self.page.evaluate(
                    "() => document.body?.innerText?.slice(0, 8000) || ''"
                )
        else:
            raise ValueError(f"unknown info type: {what}")

    # -- Select/Check (F10) --

    async def select_option(self, selector: str, value: str) -> str:
        """Select an option from a <select> element.

        Hover before selecting for human-like behavior.
        """
        if self.page is None:
            raise RuntimeError("browser not launched")

        resolved = self._resolve_selector(selector)
        css, frame_index = resolved
        locator = await self._get_locator(selector, _resolved=resolved)

        # Human-like: hover first (works for both main frame and iframes)
        await locator.hover()
        await asyncio.sleep(0.1)

        await locator.select_option(value)
        return f"selected '{value}' on {selector}"

    async def check(self, selector: str) -> str:
        """Check a checkbox or radio button (F10). Hover before checking."""
        if self.page is None:
            raise RuntimeError("browser not launched")

        resolved = self._resolve_selector(selector)
        locator = await self._get_locator(selector, _resolved=resolved)

        # Human-like: hover first (works for both main frame and iframes)
        await locator.hover()
        await asyncio.sleep(0.1)

        await locator.check()
        return f"checked {selector}"

    async def uncheck(self, selector: str) -> str:
        """Uncheck a checkbox (F10). Hover before unchecking."""
        if self.page is None:
            raise RuntimeError("browser not launched")

        resolved = self._resolve_selector(selector)
        locator = await self._get_locator(selector, _resolved=resolved)

        # Human-like: hover first (works for both main frame and iframes)
        await locator.hover()
        await asyncio.sleep(0.1)

        await locator.uncheck()
        return f"unchecked {selector}"

    # -- Wait (F7) --

    async def wait_for_element(
        self, selector: str, *, timeout: int = 30000
    ) -> str:
        """Wait for an element to appear (F7)."""
        if self.page is None:
            raise RuntimeError("browser not launched")

        locator = await self._get_locator(selector)
        await locator.wait_for(state="visible", timeout=timeout)
        return f"element {selector} is visible"

    async def wait_for_text(self, text: str, *, timeout: int = 30000) -> str:
        """Wait for text to appear on the page (F7)."""
        if self.page is None:
            raise RuntimeError("browser not launched")
        locator = self.page.get_by_text(text)
        await locator.wait_for(state="visible", timeout=timeout)
        return f"text '{text}' found"

    async def wait_for_network_idle(self, *, timeout: int = 30000) -> str:
        """Wait for network to be idle (F7)."""
        if self.page is None:
            raise RuntimeError("browser not launched")
        await self.page.wait_for_load_state("networkidle", timeout=timeout)
        return "network idle"

    async def wait_for_timeout(self, ms: int) -> str:
        """Wait for a fixed duration in milliseconds (F7)."""
        if self.page is None:
            raise RuntimeError("browser not launched")
        await self.page.wait_for_timeout(ms)
        return f"waited {ms}ms"

    async def wait_for_url_pattern(
        self, pattern: str, *, timeout: int = 30000
    ) -> str:
        """Wait until the current page URL matches a glob pattern (F15).

        Thin wrapper around Playwright's ``page.wait_for_url``. Glob syntax:
        ``**`` matches multiple path segments, ``*`` matches a single
        segment. Matching is literal -- no URL normalization is performed.

        Raises TimeoutError on timeout so the daemon can surface a clean
        status=error response.
        """
        if self.page is None:
            raise RuntimeError("browser not launched")
        try:
            await self.page.wait_for_url(pattern, timeout=timeout)
        except PlaywrightTimeoutError as e:
            # Translate Playwright's timeout into a clean daemon-level error.
            # Other failures (page closed, navigation aborted, invalid glob)
            # bubble up as-is so the user sees the real cause.
            raise TimeoutError(
                f"timeout waiting for url pattern: {pattern}"
            ) from e
        return self.page.url

    # -- Dialog (F8) --

    async def dialog_accept(self, text: str | None = None) -> str:
        """Accept the pending dialog (F8)."""
        if self._pending_dialog is None:
            return "no dialog present"
        if text is not None:
            await self._pending_dialog.accept(text)
        else:
            await self._pending_dialog.accept()
        self._dialog_handled = True
        self._pending_dialog = None
        return "dialog accepted"

    async def dialog_dismiss(self) -> str:
        """Dismiss the pending dialog (F8)."""
        if self._pending_dialog is None:
            return "no dialog present"
        await self._pending_dialog.dismiss()
        self._dialog_handled = True
        self._pending_dialog = None
        return "dialog dismissed"

    def dialog_info(self) -> dict[str, Any]:
        """Return info about the current/last dialog (F8)."""
        if self._pending_dialog is not None:
            return {
                "present": True,
                "type": self._pending_dialog.type,
                "message": self._pending_dialog.message,
                "default_value": self._pending_dialog.default_value,
                "handled": False,
            }
        if self._last_dialog is not None:
            return {
                "present": True,
                "type": self._last_dialog.type,
                "message": self._last_dialog.message,
                "default_value": self._last_dialog.default_value,
                "handled": self._dialog_handled,
            }
        return {"present": False}

    def set_auto_dismiss(self, enabled: bool) -> str:
        """Toggle auto-dismiss mode for dialogs (F8)."""
        self._auto_dismiss_dialogs = enabled
        return f"dialog auto-dismiss {'on' if enabled else 'off'}"

    # -- Multi-tab (F11) --

    async def tab_create(self, url: str | None = None) -> dict[str, Any]:
        """Create a new tab, optionally navigating to a URL."""
        if self.context is None:
            raise RuntimeError("browser not launched")

        page = await self.context.new_page()
        tab_id = self._register_tab(page)
        self._setup_dialog_handler(page)
        self._setup_network_handler(page)

        result: dict[str, Any] = {"tab_id": tab_id}
        if url:
            await page.goto(url, wait_until="domcontentloaded")
            result["url"] = page.url
            result["title"] = await page.title()

        self._clear_refs()
        return result

    async def tab_close(self, tab_id: int | None = None) -> str:
        """Close a tab. If tab_id is None, close the active tab."""
        if tab_id is None:
            tab_id = self._active_tab_id

        tab = self._tabs.get(tab_id)
        if tab is None:
            raise ValueError(f"tab {tab_id} not found")

        await tab.page.close()
        del self._tabs[tab_id]

        # Switch to another tab if we closed the active one
        if tab_id == self._active_tab_id:
            if self._tabs:
                self._active_tab_id = next(iter(self._tabs))
            # If no tabs remain, context is still alive and can create new pages

        self._clear_refs()
        return f"closed tab {tab_id}"

    def tab_switch(self, tab_id: int) -> str:
        """Switch to a different tab."""
        if tab_id not in self._tabs:
            raise ValueError(f"tab {tab_id} not found")
        self._active_tab_id = tab_id
        self._clear_refs()
        return f"switched to tab {tab_id}"

    async def tab_list(self) -> list[dict[str, Any]]:
        """List all open tabs (PRD: ID, URL, title, active)."""
        result = []
        for tid, tab in self._tabs.items():
            title = await tab.page.title()
            result.append({
                "tab_id": tid,
                "url": tab.page.url,
                "title": title,
                "active": tid == self._active_tab_id,
            })
        return result

    # -- CAPTCHA --

    async def solve_captcha(self) -> dict[str, Any]:
        """Detect and attempt to solve any CAPTCHA on the page."""
        if self.captcha is None:
            raise RuntimeError("browser not launched")
        result = await self.captcha.solve()
        return {
            "solved": result.solved,
            "message": result.message,
            "screenshot": result.screenshot_path,
        }

    # -- Status --

    async def status(self) -> dict[str, Any]:
        """Return daemon/browser status."""
        return {
            "browser_connected": self.is_alive,
            "headed": self._headed,
            "current_url": self.page.url if self.page else None,
            "current_site": self._current_site,
            "active_tab": self._active_tab_id,
            "tab_count": len(self._tabs),
        }
