"""F15 tracer: validate Patchright page.wait_for_url glob semantics.

Tests:
1. Already-on-target URL -> immediate return (no navigation needed)
2. Glob pattern matching: **/path, https://**.example.com/**, full URL
3. Cross-origin redirect (example.com -> iana.org)
4. Timeout when pattern never matches -> raises TimeoutError
"""

from __future__ import annotations

import asyncio
import time

from patchright.async_api import async_playwright


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            channel="chrome",
        )
        ctx = await browser.new_context()
        page = await ctx.new_page()

        print("== F15: wait_for_url glob ==")

        # Case 1: navigate then wait_for_url already matching (immediate return)
        await page.goto("https://example.com")
        print(f"  current url: {page.url}")
        t0 = time.monotonic()
        await page.wait_for_url("**example.com**", timeout=3000)
        dt = time.monotonic() - t0
        print(f"  ✓ already-matching pattern '**example.com**' returned in {dt*1000:.1f} ms")

        # Case 2: glob with path segment
        t0 = time.monotonic()
        try:
            await page.wait_for_url("**/index.html", timeout=1500)
            print(f"  pattern '**/index.html' matched in {(time.monotonic()-t0)*1000:.1f} ms (vs {page.url})")
        except Exception as e:
            print(f"  pattern '**/index.html' did NOT match {page.url}: {type(e).__name__}")

        # Case 3: cross-origin redirect — example.com homepage has a link to iana.org
        # Programmatic navigation to trigger
        async def nav() -> None:
            await asyncio.sleep(0.3)
            await page.goto("https://www.iana.org/")
        nav_task = asyncio.create_task(nav())
        t0 = time.monotonic()
        try:
            await page.wait_for_url("**iana.org**", timeout=10000)
            print(f"  ✓ cross-domain wait '**iana.org**' matched in {(time.monotonic()-t0)*1000:.1f} ms, url={page.url}")
        except Exception as e:
            print(f"  ✗ cross-domain wait failed: {e}")
        await nav_task

        # Case 4: full-URL glob
        t0 = time.monotonic()
        try:
            await page.wait_for_url("https://**.iana.org/**", timeout=2000)
            print(f"  ✓ pattern 'https://**.iana.org/**' matched in {(time.monotonic()-t0)*1000:.1f} ms")
        except Exception as e:
            print(f"  ✗ pattern 'https://**.iana.org/**': {type(e).__name__}: {e}")

        # Case 5: timeout when pattern never matches
        t0 = time.monotonic()
        try:
            await page.wait_for_url("**/never-matches-this", timeout=1500)
            print("  ✗ expected timeout, got match")
        except Exception as e:
            dt = time.monotonic() - t0
            print(f"  ✓ pattern '**/never-matches-this' raised {type(e).__name__} after {dt*1000:.1f} ms")
            print(f"    msg: {str(e).splitlines()[0][:120]}")

        # Case 6: dashboard pattern (typical SPA case from PRD)
        await page.goto("https://example.com")
        async def goto_dash() -> None:
            await asyncio.sleep(0.3)
            await page.goto("https://www.iana.org/help/example-domains")
        nav_task = asyncio.create_task(goto_dash())
        t0 = time.monotonic()
        try:
            await page.wait_for_url("**/help/**", timeout=8000)
            print(f"  ✓ pattern '**/help/**' matched in {(time.monotonic()-t0)*1000:.1f} ms, url={page.url}")
        except Exception as e:
            print(f"  ✗ pattern '**/help/**' failed: {e}")
        await nav_task

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
