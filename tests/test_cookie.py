"""
Tracer bullet: Verify pycookiecheat Cookie extraction + Patchright injection.

Tests:
1. Extract cookies from macOS Chrome for x.com
2. Convert to Playwright format and inject into Patchright context
3. Navigate to x.com/home and check if logged-in state is preserved
"""

from patchright.sync_api import sync_playwright

CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)

TARGET_URL = "https://x.com"
TARGET_PAGE = "https://x.com/home"


def extract_cookies():
    """Extract cookies from Chrome using pycookiecheat."""
    print("Extracting cookies from Chrome...")

    # Use as_cookies=True to get full cookie objects with metadata.
    # pycookiecheat 0.8.x returns pycookiecheat.common.Cookie dataclass objects,
    # NOT http.cookiejar.Cookie. Key differences:
    #   - host_key (not domain)
    #   - expires_utc (not expires)
    #   - is_secure (not secure)
    #   - no httpOnly attribute
    from pycookiecheat import BrowserType, get_cookies

    cookies = get_cookies(TARGET_URL, browser=BrowserType.CHROME, as_cookies=True)
    print(f"Extracted {len(cookies)} cookies (pycookiecheat.common.Cookie)")

    pw_cookies = []
    for c in cookies:
        # Chrome stores expires as microseconds since 1601-01-01.
        # Playwright expects Unix epoch seconds or -1 for session cookies.
        if c.expires_utc and c.expires_utc > 0:
            expires_unix = (c.expires_utc / 1_000_000) - 11644473600
            expires = int(max(expires_unix, 0))
        else:
            expires = -1

        pw_cookies.append(
            {
                "name": c.name,
                "value": c.value,
                "domain": c.host_key,
                "path": c.path,
                "expires": expires,
                "httpOnly": False,  # pycookiecheat doesn't expose httpOnly
                "secure": bool(c.is_secure),
                "sameSite": "Lax",
            }
        )
    return pw_cookies


def main():
    # Step 1: Extract cookies
    try:
        pw_cookies = extract_cookies()
    except Exception as e:
        print(f"FAIL: Cookie extraction failed: {e}")
        print("This may be a Keychain permission issue. Grant access and retry.")
        return

    if not pw_cookies:
        print("FAIL: No cookies extracted. Are you logged into x.com in Chrome?")
        return

    # Print cookie summary (names and domains only, not values)
    domains = set(c["domain"] for c in pw_cookies)
    print(f"\nCookie summary: {len(pw_cookies)} cookies across domains: {domains}")
    print("Cookie names:", [c["name"] for c in pw_cookies])

    # Step 2: Launch Patchright and inject cookies
    print("\nLaunching Patchright with system Chrome...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chrome")
        context = browser.new_context(user_agent=CHROME_UA)

        # Inject cookies
        print(f"Injecting {len(pw_cookies)} cookies...")
        try:
            context.add_cookies(pw_cookies)
            print("PASS: Cookies injected successfully")
        except Exception as e:
            print(f"FAIL: Cookie injection failed: {e}")
            browser.close()
            return

        # Step 3: Navigate and check login state
        page = context.new_page()
        print(f"\nNavigating to {TARGET_PAGE}...")
        page.goto(TARGET_PAGE, wait_until="domcontentloaded", timeout=30000)

        # Wait a bit for any redirects
        page.wait_for_timeout(3000)

        final_url = page.url
        title = page.title()
        print(f"Final URL: {final_url}")
        print(f"Page title: {title}")

        # Check if we're logged in or redirected to login
        if "login" in final_url.lower() or "flow" in final_url.lower():
            print("FAIL: Redirected to login page -- cookies didn't maintain session")
        elif "home" in final_url.lower():
            print("PASS: Stayed on /home -- login state preserved")
        else:
            print(f"WARN: Unexpected URL: {final_url}")

        # Screenshot for visual verification
        page.screenshot(path="/tmp/cookie-test-twitter.png", full_page=True)
        print("Screenshot saved to /tmp/cookie-test-twitter.png")

        browser.close()
        print("\nDone.")


if __name__ == "__main__":
    main()
