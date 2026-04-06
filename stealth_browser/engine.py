"""Patchright browser engine -- launch, context, page management.

Key constraints (tracer-verified):
- Must use channel='chrome' (system Chrome), not bundled Chromium
- Headless UA still contains "HeadlessChrome" -- must override in new_context()
- Must use patchright.async_api for daemon architecture (sync API greenlet issue)
- Cookie injection: after new_context(), before first goto()
"""

from __future__ import annotations

import logging
import os
from typing import Any

from patchright.async_api import Browser, BrowserContext, Page, Playwright
from patchright.async_api import async_playwright

from .behavior import HumanBehavior
from .captcha import CaptchaSolver
from .cookies import clear_cache, get_cookies_for_site
from .utils import get_chrome_ua, is_login_redirect, warn

logger = logging.getLogger("stealth_browser.engine")


class StealthEngine:
    """Manages a Patchright browser instance with anti-detection configuration.

    Provides the async API used by the daemon to handle CLI commands.
    """

    def __init__(self) -> None:
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.behavior: HumanBehavior | None = None
        self.captcha: CaptchaSolver | None = None
        self._current_site: str | None = None
        self._headed: bool = False

    async def launch(self, *, headed: bool = False) -> None:
        """Launch the browser with anti-detection configuration."""
        self._headed = headed
        self.playwright = await async_playwright().start()

        # System Chrome is required -- bundled Chromium leaks 11+ detection signals
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

        # Create context with realistic UA (overrides HeadlessChrome in headless mode)
        self.context = await self.browser.new_context(
            user_agent=get_chrome_ua(),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )

        self.page = await self.context.new_page()
        self.behavior = HumanBehavior(self.page, fast=False)
        self.captcha = CaptchaSolver(self.page, self.behavior)
        logger.info("browser launched (headed=%s)", headed)

    async def shutdown(self) -> None:
        """Close browser and clean up."""
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
        self.page = None
        self.context = None
        self.behavior = None
        self.captcha = None
        logger.info("browser shut down")

    @property
    def is_alive(self) -> bool:
        return self.browser is not None and self.browser.is_connected()

    async def inject_cookies(self, site: str, url: str) -> int:
        """Extract/load cookies for a site and inject into the browser context.

        Returns the number of cookies injected.
        """
        if self.context is None:
            raise RuntimeError("browser not launched")

        cookies = get_cookies_for_site(site, url)
        if not cookies:
            return 0

        await self.context.add_cookies(cookies)
        self._current_site = site
        return len(cookies)

    async def navigate(
        self, url: str, *, site: str | None = None, timeout: int = 30000
    ) -> dict[str, Any]:
        """Navigate to a URL. If site is given, inject cookies first.

        Returns dict with url, title, and login_redirect flag.
        After navigation, checks for login redirect (session expiry).
        If detected and site is set, re-extracts cookies and retries once.
        """
        if self.page is None:
            raise RuntimeError("browser not launched")

        if site and self._current_site != site:
            count = await self.inject_cookies(site, url)
            logger.info("injected %d cookies for %s", count, site)

        await self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        # Brief wait for redirects to settle
        await self.page.wait_for_timeout(2000)

        final_url = self.page.url
        title = await self.page.title()

        # Check for login redirect
        if is_login_redirect(final_url) and site:
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
                    # Still redirecting after re-extract -- session truly expired
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

    async def snapshot(self, *, interactive: bool = False) -> str:
        """Return a text snapshot of the page.

        If interactive=True, includes interactive elements (links, buttons, inputs)
        with indices for easy reference.
        """
        if self.page is None:
            raise RuntimeError("browser not launched")

        # Basic page info
        url = self.page.url
        title = await self.page.title()
        lines = [f"URL: {url}", f"Title: {title}", ""]

        if interactive:
            # List interactive elements with indices
            elements = await self.page.evaluate("""() => {
                const selectors = 'a, button, input, select, textarea, [role="button"], [onclick]';
                const els = document.querySelectorAll(selectors);
                return Array.from(els).map((el, i) => {
                    const tag = el.tagName.toLowerCase();
                    const text = el.textContent?.trim().slice(0, 80) || '';
                    const type = el.getAttribute('type') || '';
                    const name = el.getAttribute('name') || '';
                    const href = el.getAttribute('href') || '';
                    const placeholder = el.getAttribute('placeholder') || '';
                    const role = el.getAttribute('role') || '';
                    const value = el.value || '';
                    const ariaLabel = el.getAttribute('aria-label') || '';

                    let desc = `[${i}] <${tag}`;
                    if (type) desc += ` type="${type}"`;
                    if (name) desc += ` name="${name}"`;
                    if (role) desc += ` role="${role}"`;
                    if (placeholder) desc += ` placeholder="${placeholder}"`;
                    desc += '>';
                    if (text && tag !== 'input' && tag !== 'textarea') desc += ' ' + text;
                    if (value && (tag === 'input' || tag === 'textarea')) desc += ' value="' + value.slice(0, 40) + '"';
                    if (href) desc += ' -> ' + href.slice(0, 80);
                    if (ariaLabel) desc += ' [' + ariaLabel + ']';
                    return desc;
                });
            }""")
            lines.append(f"Interactive elements ({len(elements)}):")
            for el in elements:
                lines.append(f"  {el}")
        else:
            # Plain text content
            text = await self.page.evaluate("""() => {
                return document.body?.innerText?.slice(0, 4000) || '';
            }""")
            lines.append(text)

        return "\n".join(lines)

    async def click(self, selector: str) -> str:
        """Click an element with human behavior simulation."""
        if self.behavior is None:
            raise RuntimeError("browser not launched")
        await self.behavior.click(selector)
        await self.page.wait_for_timeout(500)
        return f"clicked {selector}"

    async def fill(self, selector: str, text: str) -> str:
        """Fill an input with human-like typing."""
        if self.behavior is None:
            raise RuntimeError("browser not launched")
        await self.behavior.fill(selector, text)
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
        locator = self.page.locator(selector)
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

    async def eval_js(self, expression: str) -> Any:
        """Evaluate JavaScript on the page and return the result."""
        if self.page is None:
            raise RuntimeError("browser not launched")
        return await self.page.evaluate(expression)

    async def get_info(self, what: str, selector: str | None = None) -> str:
        """Get information from the page.

        what: "text", "url", "title"
        selector: optional CSS selector (for "text" mode)
        """
        if self.page is None:
            raise RuntimeError("browser not launched")

        if what == "url":
            return self.page.url
        elif what == "title":
            return await self.page.title()
        elif what == "text":
            if selector:
                locator = self.page.locator(selector)
                return await locator.inner_text()
            else:
                return await self.page.evaluate(
                    "() => document.body?.innerText?.slice(0, 8000) || ''"
                )
        else:
            raise ValueError(f"unknown info type: {what}")

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

    async def status(self) -> dict[str, Any]:
        """Return daemon/browser status."""
        return {
            "browser_connected": self.is_alive,
            "headed": self._headed,
            "current_url": self.page.url if self.page else None,
            "current_site": self._current_site,
        }
