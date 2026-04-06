"""Daemon process: asyncio HTTP server over Unix domain socket.

Keeps the Patchright browser alive across multiple CLI invocations.
Life cycle:
- First CLI command auto-starts the daemon (fork to background)
- Commands arrive as HTTP POST over Unix socket
- Idle 30 minutes -> auto-shutdown
- `close` command -> explicit shutdown
- PID file at ~/.stealth-browser/{session}.pid
- Socket at ~/.stealth-browser/{session}.sock

Must use patchright.async_api (sync API greenlet can't cross threads).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from typing import Any

from .engine import StealthEngine
from .utils import ensure_dirs, pid_path, socket_path

logger = logging.getLogger("stealth_browser.daemon")

IDLE_TIMEOUT_SECONDS = 1800  # 30 minutes


class DaemonProtocol(asyncio.Protocol):
    """HTTP/1.1 protocol handler for daemon commands over Unix socket."""

    def __init__(self, handler: DaemonHandler):
        self.handler = handler
        self.transport: asyncio.Transport | None = None
        self.buffer = b""

    def connection_made(self, transport: asyncio.Transport) -> None:
        self.transport = transport

    def data_received(self, data: bytes) -> None:
        self.buffer += data
        if b"\r\n\r\n" in self.buffer:
            asyncio.ensure_future(self._process())

    async def _process(self) -> None:
        try:
            raw = self.buffer.decode("utf-8", errors="replace")

            # Parse content-length
            content_length = 0
            for line in raw.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    content_length = int(line.split(":", 1)[1].strip())

            header_end = raw.index("\r\n\r\n") + 4
            body_str = raw[header_end: header_end + content_length]
            body = json.loads(body_str) if body_str.strip() else {}

            result = await self.handler.handle(body)
            resp_body = json.dumps(result)
            status = "200 OK"

        except Exception as e:
            resp_body = json.dumps({"status": "error", "error": str(e)})
            status = "500 Internal Server Error"
            logger.exception("command error")

        response = (
            f"HTTP/1.1 {status}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(resp_body.encode())}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
            f"{resp_body}"
        )
        if self.transport:
            self.transport.write(response.encode())
            self.transport.close()


class DaemonHandler:
    """Routes commands to the StealthEngine and manages idle timeout."""

    def __init__(self, engine: StealthEngine, session: str):
        self.engine = engine
        self.session = session
        self._last_activity = time.time()

    def touch(self) -> None:
        self._last_activity = time.time()

    @property
    def idle_seconds(self) -> float:
        return time.time() - self._last_activity

    async def handle(self, body: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a command to the engine."""
        self.touch()
        command = body.get("command", "")

        try:
            if command == "open":
                result = await self.engine.navigate(
                    body["url"],
                    site=body.get("site"),
                    timeout=body.get("timeout", 30000),
                )
                return {"status": "ok", **result}

            elif command == "snapshot":
                text = await self.engine.snapshot(
                    interactive=body.get("interactive", False)
                )
                return {"status": "ok", "content": text}

            elif command == "click":
                msg = await self.engine.click(body["selector"])
                return {"status": "ok", "message": msg}

            elif command == "fill":
                msg = await self.engine.fill(body["selector"], body["text"])
                return {"status": "ok", "message": msg}

            elif command == "type":
                msg = await self.engine.type_text(body["text"])
                return {"status": "ok", "message": msg}

            elif command == "scroll":
                msg = await self.engine.scroll(
                    body.get("direction", "down"),
                    body.get("amount", 3),
                )
                return {"status": "ok", "message": msg}

            elif command == "upload":
                msg = await self.engine.upload(body["selector"], body["file"])
                return {"status": "ok", "message": msg}

            elif command == "screenshot":
                path = await self.engine.screenshot(body.get("path"))
                return {"status": "ok", "path": path}

            elif command == "eval":
                value = await self.engine.eval_js(body["expression"])
                return {"status": "ok", "value": value}

            elif command == "get":
                text = await self.engine.get_info(
                    body["what"], body.get("selector")
                )
                return {"status": "ok", "value": text}

            elif command == "status":
                info = await self.engine.status()
                return {"status": "ok", **info}

            elif command == "captcha":
                result = await self.engine.solve_captcha()
                return {"status": "ok", **result}

            elif command == "cookie_refresh":
                site = body.get("site")
                if not site:
                    return {"status": "error", "error": "site required for cookie refresh"}
                from .cookies import clear_cache
                clear_cache(site)
                url = self.engine.page.url if self.engine.page else f"https://{site}"
                count = await self.engine.inject_cookies(site, url)
                return {"status": "ok", "message": f"refreshed {count} cookies for {site}"}

            elif command == "close":
                # Schedule shutdown after sending response
                asyncio.get_event_loop().call_soon(self._schedule_shutdown)
                return {"status": "ok", "message": "shutting down"}

            elif command == "ping":
                return {"status": "ok", "message": "pong"}

            else:
                return {"status": "error", "error": f"unknown command: {command}"}

        except Exception as e:
            logger.exception(f"command '{command}' failed")
            return {"status": "error", "error": str(e)}

    def _schedule_shutdown(self) -> None:
        asyncio.ensure_future(self._shutdown())

    async def _shutdown(self) -> None:
        await asyncio.sleep(0.1)  # Let the response flush
        await self.engine.shutdown()
        _cleanup_files(self.session)
        os._exit(0)


def _cleanup_files(session: str) -> None:
    """Remove socket and PID files."""
    for path in [socket_path(session), pid_path(session)]:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


async def _run_daemon(session: str, headed: bool) -> None:
    """Main daemon coroutine: start engine + server, run until shutdown."""
    engine = StealthEngine()
    await engine.launch(headed=headed)

    handler = DaemonHandler(engine, session)
    loop = asyncio.get_event_loop()

    sock = socket_path(session)
    sock.unlink(missing_ok=True)

    server = await loop.create_unix_server(
        lambda: DaemonProtocol(handler), path=str(sock)
    )
    # Make socket accessible
    sock.chmod(0o600)

    logger.info(f"daemon listening on {sock}")

    # Idle timeout checker
    async def idle_checker() -> None:
        while True:
            await asyncio.sleep(60)
            if handler.idle_seconds > IDLE_TIMEOUT_SECONDS:
                logger.info("idle timeout reached, shutting down")
                await engine.shutdown()
                _cleanup_files(session)
                server.close()
                os._exit(0)

    asyncio.ensure_future(idle_checker())

    # Handle signals
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.ensure_future(_signal_handler(engine, server, session)),
        )

    try:
        await server.serve_forever()
    except asyncio.CancelledError:
        pass
    finally:
        await engine.shutdown()
        _cleanup_files(session)


async def _signal_handler(
    engine: StealthEngine, server: asyncio.Server, session: str
) -> None:
    await engine.shutdown()
    _cleanup_files(session)
    server.close()
    os._exit(0)


def start_daemon(session: str, headed: bool = False) -> None:
    """Fork a daemon process and return immediately in the parent.

    The child process runs the asyncio event loop with the browser engine.
    """
    ensure_dirs()
    sock = socket_path(session)
    pid_file = pid_path(session)

    # Check if daemon is already running
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
            return  # Already running
        except (ProcessLookupError, ValueError):
            # Stale PID file, clean up
            pid_file.unlink(missing_ok=True)
            sock.unlink(missing_ok=True)

    # Fork
    pid = os.fork()
    if pid > 0:
        # Parent: wait briefly for daemon to start, then return
        _wait_for_socket(session, timeout=15.0)
        return

    # Child: become session leader (detach from terminal)
    os.setsid()

    # Second fork to fully daemonize
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)

    # Grandchild: the actual daemon process
    # Redirect stdio
    sys.stdin.close()
    devnull = open(os.devnull, "w")
    sys.stdout = devnull
    sys.stderr = devnull

    # Write PID file
    pid_file.write_text(str(os.getpid()))
    pid_file.chmod(0o600)

    # Configure logging to file
    log_file = socket_path(session).with_suffix(".log")
    logging.basicConfig(
        filename=str(log_file),
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Run the daemon
    asyncio.run(_run_daemon(session, headed))
    os._exit(0)


def _wait_for_socket(session: str, timeout: float = 15.0) -> None:
    """Block until the daemon's Unix socket appears, or timeout."""
    import time

    sock = socket_path(session)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if sock.exists():
            # Try a ping to confirm it's responsive
            try:
                send_command(session, "ping")
                return
            except Exception:
                pass
        time.sleep(0.2)
    raise RuntimeError(f"daemon failed to start within {timeout}s")


def send_command(session: str, command: str, **kwargs: Any) -> dict[str, Any]:
    """Send a command to the daemon over Unix socket and return the response.

    This is a synchronous call used by the CLI process.
    """
    import http.client
    import socket as socket_module

    sock = socket_path(session)
    if not sock.exists():
        raise RuntimeError("daemon not running")

    payload = json.dumps({"command": command, **kwargs})

    # HTTP over Unix socket
    conn = http.client.HTTPConnection("localhost")
    # Replace the socket factory to use Unix domain socket
    s = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    s.settimeout(60)
    s.connect(str(sock))
    conn.sock = s

    try:
        conn.request("POST", "/", body=payload, headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
        })
        response = conn.getresponse()
        data = response.read().decode()
        return json.loads(data)
    finally:
        conn.close()


def is_daemon_running(session: str) -> bool:
    """Check if a daemon is running for the given session."""
    pf = pid_path(session)
    if not pf.exists():
        return False
    try:
        pid = int(pf.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError):
        # Clean up stale files
        pf.unlink(missing_ok=True)
        socket_path(session).unlink(missing_ok=True)
        return False
