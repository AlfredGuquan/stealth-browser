"""
Tracer bullet: Verify that a Patchright browser instance can be kept alive
across multiple HTTP requests -- proving daemon architecture is feasible.

Architecture: An asyncio event loop runs both the HTTP server and the
Patchright browser. Commands arrive via HTTP and execute on the same
event loop, avoiding the sync-API threading issue (greenlet can't cross
threads).

Tests:
1. Start daemon, open a page via HTTP command
2. Take a screenshot via a separate HTTP request (same browser instance)
3. Verify both requests used the same browser (page state persists)
"""

import asyncio
import json
import urllib.request

from patchright.async_api import async_playwright

CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)


class BrowserDaemon:
    """Minimal daemon that holds a browser instance and serves HTTP commands."""

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
        print(f"Browser started (connected={self.browser.is_connected()})")

    async def stop(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def handle_command(self, command, params):
        if command == "goto":
            await self.page.goto(
                params["url"], wait_until="domcontentloaded", timeout=15000
            )
            return {"url": self.page.url, "title": await self.page.title()}

        elif command == "screenshot":
            path = params.get("path", "/tmp/daemon-test.png")
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
    """Minimal HTTP/1.1 protocol handler for the daemon."""

    def __init__(self, daemon):
        self.daemon = daemon
        self.transport = None
        self.buffer = b""

    def connection_made(self, transport):
        self.transport = transport

    def data_received(self, data):
        self.buffer += data
        # Wait for full request (simple: look for double CRLF)
        if b"\r\n\r\n" not in self.buffer:
            return
        asyncio.ensure_future(self._process_request())

    async def _process_request(self):
        try:
            raw = self.buffer.decode()
            # Parse content length
            content_length = 0
            for line in raw.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    content_length = int(line.split(":")[1].strip())

            # Extract body
            header_end = raw.index("\r\n\r\n") + 4
            body_str = raw[header_end : header_end + content_length]
            body = json.loads(body_str) if body_str else {}

            command = body.get("command", "")
            result = await self.daemon.handle_command(command, body)
            response_body = json.dumps({"status": "ok", **result})
            status = "200 OK"

        except Exception as e:
            response_body = json.dumps({"status": "error", "message": str(e)})
            status = "500 Internal Server Error"

        response = (
            f"HTTP/1.1 {status}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(response_body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
            f"{response_body}"
        )
        self.transport.write(response.encode())
        self.transport.close()


def send_command(port, command, **kwargs):
    """Send a command to the daemon and return the response."""
    payload = json.dumps({"command": command, **kwargs}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


async def run_daemon_and_test():
    port = 19284
    daemon = BrowserDaemon()

    # Start browser
    print("Starting browser...")
    await daemon.start()

    # Start async TCP server
    loop = asyncio.get_event_loop()
    server = await loop.create_server(
        lambda: HTTPProtocol(daemon), "127.0.0.1", port
    )
    print(f"Daemon listening on http://127.0.0.1:{port}")

    try:
        # Run test commands in a thread to avoid blocking the event loop
        # (urllib is sync, but that simulates real CLI client behavior)
        def run_tests():
            # --- Request 1: Navigate to a page ---
            print("\n[Request 1] goto example.com")
            r1 = send_command(port, "goto", url="https://example.com")
            print(f"  Response: {r1}")
            assert r1["status"] == "ok"
            assert "example" in r1["title"].lower()
            print("  PASS: Page opened successfully")

            # --- Request 2: Check status (browser still alive?) ---
            print("\n[Request 2] status check")
            r2 = send_command(port, "status")
            print(f"  Response: {r2}")
            assert r2["browser_connected"] is True
            assert r2["current_url"] == r1["url"]
            print("  PASS: Browser persisted between requests, same page state")

            # --- Request 3: Screenshot ---
            print("\n[Request 3] screenshot")
            r3 = send_command(port, "screenshot", path="/tmp/daemon-test.png")
            print(f"  Response: {r3}")
            assert r3["status"] == "ok"
            print("  PASS: Screenshot taken from persistent browser")

            # --- Request 4: Eval JS ---
            print("\n[Request 4] eval document.title")
            r4 = send_command(port, "eval", expression="document.title")
            print(f"  Response: {r4}")
            assert "example" in r4["value"].lower()
            print("  PASS: JS eval works on persistent page")

            # --- Request 5: Navigate to second page ---
            print("\n[Request 5] goto httpbin")
            r5 = send_command(port, "goto", url="https://httpbin.org/get")
            print(f"  Response: {r5}")
            assert r5["status"] == "ok"
            print("  PASS: Navigation to second page succeeded")

            # --- Request 6: Verify state updated ---
            print("\n[Request 6] status after second navigation")
            r6 = send_command(port, "status")
            print(f"  Response: {r6}")
            assert "httpbin" in r6["current_url"]
            print("  PASS: Browser state updated to new page")

            print("\n=== ALL TESTS PASSED ===")
            print(
                "Daemon architecture is feasible: browser instance persists"
            )
            print("across multiple HTTP requests with full state retention.")

        await loop.run_in_executor(None, run_tests)

    finally:
        print("\nShutting down...")
        server.close()
        await server.wait_closed()
        await daemon.stop()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(run_daemon_and_test())
