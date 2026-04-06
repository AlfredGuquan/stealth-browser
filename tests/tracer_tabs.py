"""
Tracer bullet: Validate multi-tab architecture for V2 F11.

Experiments:
1. Multi-page in single context — can one BrowserContext hold multiple pages?
2. Cookie injection scope — context.add_cookies() domain scoping behavior
3. HumanBehavior page swap — can we reassign page reference or need new instance?
4. Page close isolation — does closing one page affect others?

Run: uv run python tests/tracer_tabs.py
"""

import asyncio
import sys
import traceback

from patchright.async_api import async_playwright

# Suppress humanization-playwright's loguru file handler
try:
    from loguru import logger as _loguru_logger
    _loguru_logger.remove()
except ImportError:
    pass

from stealth_browser.behavior import HumanBehavior

CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)

results = {}


def report(experiment: str, passed: bool, evidence: str) -> None:
    status = "PASS" if passed else "FAIL"
    results[experiment] = (passed, evidence)
    print(f"\n{'=' * 60}")
    print(f"[{status}] {experiment}")
    print(f"  Evidence: {evidence}")
    print(f"{'=' * 60}")


async def experiment_1_multi_page(context) -> tuple:
    """Can a single BrowserContext hold multiple independent pages?"""
    print("\n--- Experiment 1: Multi-page in single context ---")

    page1 = await context.new_page()
    page2 = await context.new_page()

    await page1.goto("https://example.com", wait_until="domcontentloaded")
    await page2.goto("https://httpbin.org/html", wait_until="domcontentloaded")

    url1 = page1.url
    url2 = page2.url
    title1 = await page1.title()
    title2 = await page2.title()

    print(f"  page1: url={url1}, title={title1!r}")
    print(f"  page2: url={url2}, title={title2!r}")

    # Both pages alive?
    pages_in_context = context.pages
    print(f"  context.pages count: {len(pages_in_context)}")

    # Can we read from page1 after creating/navigating page2?
    body1 = await page1.evaluate("() => document.body.innerText.slice(0, 100)")
    body2 = await page2.evaluate("() => document.body.innerText.slice(0, 100)")
    print(f"  page1 body: {body1[:60]!r}")
    print(f"  page2 body: {body2[:60]!r}")

    passed = (
        "example.com" in url1
        and "httpbin.org" in url2
        and len(pages_in_context) >= 2
        and len(body1) > 0
        and len(body2) > 0
    )

    evidence = (
        f"page1={url1}, page2={url2}, "
        f"context.pages={len(pages_in_context)}, "
        f"both bodies non-empty"
    )
    report("Experiment 1: Multi-page in single context", passed, evidence)
    return page1, page2


async def experiment_2_cookie_scope(context, page1, page2) -> None:
    """Does context.add_cookies() affect all pages or is it domain-scoped?"""
    print("\n--- Experiment 2: Cookie injection scope ---")

    # Add cookie for example.com
    await context.add_cookies([{
        "name": "tracer_test",
        "value": "hello_from_example",
        "domain": ".example.com",
        "path": "/",
    }])

    # Check from page1 (example.com) — should see it
    cookies_page1 = await page1.evaluate("() => document.cookie")
    print(f"  page1 (example.com) cookies: {cookies_page1!r}")

    # Check from page2 (httpbin.org) — should NOT see it
    cookies_page2 = await page2.evaluate("() => document.cookie")
    print(f"  page2 (httpbin.org) cookies: {cookies_page2!r}")

    # Now add cookie for httpbin.org
    await context.add_cookies([{
        "name": "tracer_test",
        "value": "hello_from_httpbin",
        "domain": ".httpbin.org",
        "path": "/",
    }])

    # Verify page2 now sees its cookie
    cookies_page2_after = await page2.evaluate("() => document.cookie")
    print(f"  page2 (httpbin.org) after add: {cookies_page2_after!r}")

    # Verify page1 still only sees example.com cookie, not httpbin's
    cookies_page1_after = await page1.evaluate("() => document.cookie")
    print(f"  page1 (example.com) after httpbin add: {cookies_page1_after!r}")

    # Also check via context.cookies() API for full picture
    all_cookies = await context.cookies()
    print(f"  context.cookies() count: {len(all_cookies)}")
    for c in all_cookies:
        print(f"    {c['name']}={c['value']} domain={c['domain']}")

    p1_sees_own = "tracer_test" in cookies_page1
    p2_no_leak = "hello_from_example" not in cookies_page2
    p2_sees_own = "tracer_test" in cookies_page2_after
    p1_no_leak = "hello_from_httpbin" not in cookies_page1_after

    passed = p1_sees_own and p2_no_leak and p2_sees_own and p1_no_leak
    evidence = (
        f"page1 sees own cookie: {p1_sees_own}, "
        f"page2 no leak from example.com: {p2_no_leak}, "
        f"page2 sees own cookie: {p2_sees_own}, "
        f"page1 no leak from httpbin: {p1_no_leak}"
    )
    report("Experiment 2: Cookie injection scope", passed, evidence)


async def experiment_3_behavior_swap(page1, page2) -> None:
    """Can HumanBehavior swap its page reference, or do we need new instances?"""
    print("\n--- Experiment 3: HumanBehavior page swap ---")

    # Strategy A: Direct attribute reassignment
    print("  Strategy A: Direct page attribute swap")
    hb = HumanBehavior(page1, fast=True)

    # Verify it's bound to page1
    bound_url_before = hb.page.url
    print(f"    hb.page.url before swap: {bound_url_before}")

    # Swap to page2
    hb.page = page2
    hb._h.page = page2
    bound_url_after = hb.page.url
    print(f"    hb.page.url after swap: {bound_url_after}")

    # Can we perform an action on page2 via the swapped behavior?
    # Use scroll (doesn't need a specific element)
    try:
        await hb.scroll("down", 1)
        scroll_ok = True
        print("    scroll on swapped page: OK")
    except Exception as e:
        scroll_ok = False
        print(f"    scroll on swapped page: FAILED — {e}")

    # Strategy B: New instance per page
    print("  Strategy B: New instance per page")
    hb1 = HumanBehavior(page1, fast=True)
    hb2 = HumanBehavior(page2, fast=True)

    try:
        await hb1.scroll("down", 1)
        hb1_ok = True
        print("    hb1 scroll: OK")
    except Exception as e:
        hb1_ok = False
        print(f"    hb1 scroll: FAILED — {e}")

    try:
        await hb2.scroll("down", 1)
        hb2_ok = True
        print("    hb2 scroll: OK")
    except Exception as e:
        hb2_ok = False
        print(f"    hb2 scroll: FAILED — {e}")

    swap_works = "httpbin.org" in bound_url_after and scroll_ok
    new_instance_works = hb1_ok and hb2_ok

    passed = swap_works and new_instance_works
    evidence = (
        f"swap works: {swap_works} (url={bound_url_after}, scroll_ok={scroll_ok}), "
        f"new instance per page: {new_instance_works}"
    )
    report("Experiment 3: HumanBehavior page swap", passed, evidence)

    # Recommendation
    if swap_works and new_instance_works:
        print("  Recommendation: New instance per page is cleaner (no risk of "
              "stale internal state in Humanization). Swap works as fallback.")
    elif new_instance_works:
        print("  Recommendation: Must use new instance per page — swap fails.")
    else:
        print("  WARNING: Neither strategy fully works — needs investigation.")


async def experiment_4_close_isolation(context, page1, page2) -> None:
    """Does closing one page affect the context or other pages?"""
    print("\n--- Experiment 4: Page close isolation ---")

    pages_before = len(context.pages)
    print(f"  pages before close: {pages_before}")

    # Close page2
    await page2.close()
    print("  closed page2")

    pages_after = len(context.pages)
    print(f"  pages after close: {pages_after}")

    # page1 still alive?
    try:
        p1_url = page1.url
        p1_title = await page1.title()
        p1_alive = True
        print(f"  page1 alive: url={p1_url}, title={p1_title!r}")
    except Exception as e:
        p1_alive = False
        print(f"  page1 alive: FAILED — {e}")

    # context still alive?
    try:
        page3 = await context.new_page()
        await page3.goto("https://example.com", wait_until="domcontentloaded")
        p3_url = page3.url
        context_alive = True
        print(f"  context alive, created page3: url={p3_url}")
        pages_final = len(context.pages)
        print(f"  pages final count: {pages_final}")
        await page3.close()
    except Exception as e:
        context_alive = False
        print(f"  context new page: FAILED — {e}")

    # Check page2 is truly closed
    try:
        await page2.title()
        p2_closed = False
        print("  page2 still responds (unexpected)")
    except Exception:
        p2_closed = True
        print("  page2 confirmed closed (raises on access)")

    passed = p1_alive and context_alive and p2_closed
    evidence = (
        f"page1 alive: {p1_alive}, "
        f"context can create new pages: {context_alive}, "
        f"page2 confirmed closed: {p2_closed}"
    )
    report("Experiment 4: Page close isolation", passed, evidence)


async def main() -> int:
    print("Tracer Bullet: Multi-Tab Architecture Validation")
    print("=" * 60)

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        channel="chrome",
    )
    context = await browser.new_context(
        user_agent=CHROME_UA,
        viewport={"width": 1920, "height": 1080},
    )

    try:
        # Experiment 1
        page1, page2 = await experiment_1_multi_page(context)

        # Experiment 2
        await experiment_2_cookie_scope(context, page1, page2)

        # Experiment 3
        await experiment_3_behavior_swap(page1, page2)

        # Experiment 4
        await experiment_4_close_isolation(context, page1, page2)

    except Exception:
        traceback.print_exc()
    finally:
        await browser.close()
        await pw.stop()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_pass = True
    for name, (passed, evidence) in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            all_pass = False

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
