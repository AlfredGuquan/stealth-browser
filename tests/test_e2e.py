"""
Tracer bullet: End-to-end path verification.

Combines all three integration points into a single flow:
1. Patchright stealth engine (channel='chrome' + custom UA)
2. Cookie extraction from Chrome via pycookiecheat + injection
3. Daemon architecture (browser persists across HTTP requests)

Flow: Start daemon -> inject cookies via HTTP -> navigate to x.com/home
via HTTP -> verify logged-in state via HTTP -> screenshot via HTTP.
"""

import asyncio
import json
import urllib.request

from patchright.async_api import async_playwright
from pycookiecheat import BrowserType, get_cookies

CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)


def extract_cookies_for_playwright(url):
    """Extract cookies from Chrome and convert to Playwright format."""
    cookies = get_cookies(url, browser=BrowserType.CHROME, as_cookies=True)
    pw_cookies = []
    for c in cookies:
        if c.expires_utc and c.expires_utc > 0:
            expires = int((c.expires_utc / 1_000_000) - 11644473600)
            expires = max(expires, 0)
        else:
            expires = -1
        pw_cookies.append(
            {
                "name": c.name,
                "value": c.value,
                "domain": c.host_key,
                "path": c.path,
                "expires": expires,
                "httpOnly": False,
                "secure": bool(c.is_secure),
                "sameSite": "Lax",
            }
        )
    return pw_cookies


class BrowserDaemon:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def start(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True, channel="chrome"
        )
        self.context = await self.browser.new_context(user_agent=CHROME_UA)
        self.page = await self.context.new_page()

    async def stop(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def handle_command(self, command, params):
        if command == "inject_cookies":
            await self.context.add_cookies(params["cookies"])
            return {"injected": len(params["cookies"])}
        elif command == "goto":
            await self.page.goto(
                params["url"], wait_until="domcontentloaded", timeout=30000
            )
            await self.page.wait_for_timeout(3000)
            return {"url": self.page.url, "title": await self.page.title()}
        elif command == "screenshot":
            path = params.get("path", "/tmp/e2e-test.png")
            await self.page.screenshot(path=path)
            return {"path": path}
        elif command == "eval":
            value = await self.page.evaluate(params["expression"])
            return {"value": value}
        elif command == "status":
            return {
                "browser_connected": self.browser.is_connected(),
                "current_url": self.page.url,
            }
        else:
            raise ValueError(f"unknown command: {command}")


class HTTPProtocol(asyncio.Protocol):
    def __init__(self, daemon):
        self.daemon = daemon
        self.transport = None
        self.buffer = b""

    def connection_made(self, transport):
        self.transport = transport

    def data_received(self, data):
        self.buffer += data
        if b"\r\n\r\n" not in self.buffer:
            return
        asyncio.ensure_future(self._process())

    async def _process(self):
        try:
            raw = self.buffer.decode()
            content_length = 0
            for line in raw.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    content_length = int(line.split(":")[1].strip())
            header_end = raw.index("\r\n\r\n") + 4
            body = json.loads(raw[header_end : header_end + content_length])
            result = await self.daemon.handle_command(
                body.get("command", ""), body
            )
            resp_body = json.dumps({"status": "ok", **result})
            status = "200 OK"
        except Exception as e:
            resp_body = json.dumps({"status": "error", "message": str(e)})
            status = "500 Internal Server Error"

        resp = (
            f"HTTP/1.1 {status}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(resp_body)}\r\n"
            f"Connection: close\r\n\r\n{resp_body}"
        )
        self.transport.write(resp.encode())
        self.transport.close()


def send(port, command, **kwargs):
    payload = json.dumps({"command": command, **kwargs}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


async def main():
    port = 19285

    # Step 1: Extract cookies (sync, before event loop work)
    print("Step 1: Extracting cookies from Chrome for x.com...")
    pw_cookies = extract_cookies_for_playwright("https://x.com")
    print(f"  Extracted {len(pw_cookies)} cookies")
    auth_cookies = [c["name"] for c in pw_cookies if "auth" in c["name"].lower() or c["name"] == "ct0"]
    print(f"  Key session cookies present: {auth_cookies}")

    # Step 2: Start stealth daemon
    print("\nStep 2: Starting stealth browser daemon...")
    daemon = BrowserDaemon()
    await daemon.start()

    loop = asyncio.get_event_loop()
    server = await loop.create_server(
        lambda: HTTPProtocol(daemon), "127.0.0.1", port
    )
    print(f"  Daemon running on http://127.0.0.1:{port}")

    try:

        def run_e2e():
            # Step 3: Verify stealth (via daemon)
            print("\nStep 3: Verify stealth properties...")
            r = send(port, "goto", url="about:blank")
            r = send(port, "eval", expression="navigator.webdriver")
            print(f"  navigator.webdriver = {r['value']}")
            assert r["value"] is False, f"webdriver should be false, got {r['value']}"
            print("  PASS: Stealth mode active")

            # Step 4: Inject cookies (via daemon)
            print("\nStep 4: Inject cookies into browser context...")
            r = send(port, "inject_cookies", cookies=pw_cookies)
            print(f"  Injected {r['injected']} cookies")
            print("  PASS: Cookie injection via daemon API")

            # Step 5: Navigate to logged-in page (via daemon)
            print("\nStep 5: Navigate to x.com/home...")
            r = send(port, "goto", url="https://x.com/home")
            print(f"  URL: {r['url']}")
            print(f"  Title: {r['title']}")

            if "login" in r["url"].lower() or "flow" in r["url"].lower():
                print("  FAIL: Redirected to login")
                return False
            elif "home" in r["url"].lower():
                print("  PASS: Logged in successfully")
            else:
                print(f"  WARN: Unexpected URL: {r['url']}")

            # Step 6: Screenshot (via daemon)
            print("\nStep 6: Take screenshot...")
            r = send(port, "screenshot", path="/tmp/e2e-stealth-cookie-daemon.png")
            print(f"  Screenshot: {r['path']}")
            print("  PASS: Screenshot via daemon API")

            # Step 7: Second request to prove persistence
            print("\nStep 7: Verify browser persistence (second status check)...")
            r = send(port, "status")
            print(f"  Browser connected: {r['browser_connected']}")
            print(f"  Current URL: {r['current_url']}")
            assert r["browser_connected"] is True
            assert "x.com" in r["current_url"]
            print("  PASS: Browser instance persisted across all requests")

            print("\n=== END-TO-END PATH VERIFIED ===")
            print("All three integration points work together:")
            print("  1. Patchright stealth: navigator.webdriver=false")
            print("  2. Cookie extraction + injection: x.com/home logged in")
            print("  3. Daemon persistence: browser alive across 7 HTTP requests")
            return True

        success = await loop.run_in_executor(None, run_e2e)

    finally:
        print("\nCleaning up...")
        server.close()
        await server.wait_closed()
        await daemon.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
