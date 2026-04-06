"""
Tracer bullet: Verify Patchright headless stealth capabilities.

Tests:
1. navigator.webdriver returns false (primary anti-detection signal)
2. Bot detection page pass rate with bundled Chromium vs system Chrome
3. Screenshot for visual inspection

Key finding: channel='chrome' (system Chrome) + custom UA = 0 failures on bot.sannysoft.com.
Bundled Chromium leaks HeadlessChrome UA, missing window.chrome, empty plugins.
"""

from patchright.sync_api import sync_playwright

# Realistic UA to replace HeadlessChrome in headless mode
CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)


def check_bot_detection(page):
    """Extract pass/fail results from bot.sannysoft.com."""
    return page.evaluate("""() => {
        const rows = document.querySelectorAll('table tr');
        const data = {};
        rows.forEach(row => {
            const cells = row.querySelectorAll('td');
            if (cells.length >= 2) {
                const key = cells[0].textContent.trim();
                const val = cells[1].textContent.trim();
                const failed = cells[1].classList.contains('failed');
                if (key) data[key] = { value: val, failed: failed };
            }
        });
        return data;
    }""")


def main():
    with sync_playwright() as p:
        # --- Config A: bundled Chromium (baseline) ---
        print("=== Config A: Bundled Chromium (headless) ===")
        browser_a = p.chromium.launch(headless=True)
        page_a = browser_a.new_context().new_page()

        webdriver_a = page_a.evaluate("() => navigator.webdriver")
        print(f"navigator.webdriver = {webdriver_a} ({'PASS' if webdriver_a is False else 'FAIL'})")

        page_a.goto("https://bot.sannysoft.com/", wait_until="networkidle")
        results_a = check_bot_detection(page_a)
        failed_a = {k: v for k, v in results_a.items() if v["failed"]}
        print(f"Results: {len(results_a) - len(failed_a)} passed, {len(failed_a)} failed")
        if failed_a:
            for k, v in failed_a.items():
                print(f"  [FAIL] {k}: {v['value']}")
        page_a.screenshot(path="/tmp/stealth-test-bundled.png", full_page=True)
        browser_a.close()

        # --- Config B: system Chrome + custom UA (recommended) ---
        print("\n=== Config B: System Chrome + custom UA (headless) ===")
        browser_b = p.chromium.launch(headless=True, channel="chrome")
        page_b = browser_b.new_context(user_agent=CHROME_UA).new_page()

        webdriver_b = page_b.evaluate("() => navigator.webdriver")
        print(f"navigator.webdriver = {webdriver_b} ({'PASS' if webdriver_b is False else 'FAIL'})")

        page_b.goto("https://bot.sannysoft.com/", wait_until="networkidle")
        results_b = check_bot_detection(page_b)
        failed_b = {k: v for k, v in results_b.items() if v["failed"]}
        print(f"Results: {len(results_b) - len(failed_b)} passed, {len(failed_b)} failed")
        if failed_b:
            for k, v in failed_b.items():
                print(f"  [FAIL] {k}: {v['value']}")
        page_b.screenshot(path="/tmp/stealth-test-chrome.png", full_page=True)
        browser_b.close()

        print("\nScreenshots: /tmp/stealth-test-bundled.png, /tmp/stealth-test-chrome.png")


if __name__ == "__main__":
    main()
