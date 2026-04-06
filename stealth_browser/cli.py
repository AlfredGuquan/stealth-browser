"""CLI interface for stealth-browser.

Designed for AI agent consumption: plain text to stdout, errors to stderr,
non-zero exit codes on failure.

Invoked as `stealth-browser <command> [args]` or `python -m stealth_browser <command>`.
"""

from __future__ import annotations

import argparse
import sys
from urllib.parse import urlparse

from .daemon import is_daemon_running, send_command, start_daemon
from .utils import error


def _site_from_url(url: str) -> str:
    """Extract a site name from a URL for session/cache partitioning."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    # Strip www. and use the domain as-is
    if host.startswith("www."):
        host = host[4:]
    return host


def _ensure_daemon(session: str, headed: bool) -> None:
    """Start the daemon if not already running."""
    if not is_daemon_running(session):
        try:
            start_daemon(session, headed=headed)
        except RuntimeError as e:
            error(f"failed to start daemon: {e}")


def _send(session: str, command: str, **kwargs) -> dict:
    """Send a command to the daemon and return the result. Exit on error."""
    try:
        result = send_command(session, command, **kwargs)
    except RuntimeError as e:
        error(str(e))
    except Exception as e:
        error(f"communication error: {e}")

    if result.get("status") == "error":
        error(result.get("error", "unknown error"))

    return result


def cmd_open(args: argparse.Namespace) -> None:
    url = args.url
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    site = args.site or _site_from_url(url)
    session = site  # One session per site

    _ensure_daemon(session, args.headed)
    result = _send(session, "open", url=url, site=site, timeout=args.timeout)

    print(f"URL: {result['url']}")
    print(f"Title: {result['title']}")

    if result.get("login_redirect"):
        print(
            f"Session expired. Please log in to {site} in Chrome and retry.",
            file=sys.stderr,
        )
        sys.exit(1)


def cmd_snapshot(args: argparse.Namespace) -> None:
    session = _get_session(args)
    result = _send(session, "snapshot", interactive=args.interactive)
    print(result["content"])


def cmd_click(args: argparse.Namespace) -> None:
    session = _get_session(args)
    result = _send(session, "click", selector=args.selector)
    print(result["message"])


def cmd_fill(args: argparse.Namespace) -> None:
    session = _get_session(args)
    result = _send(session, "fill", selector=args.selector, text=args.text)
    print(result["message"])


def cmd_type(args: argparse.Namespace) -> None:
    session = _get_session(args)
    result = _send(session, "type", text=args.text)
    print(result["message"])


def cmd_scroll(args: argparse.Namespace) -> None:
    session = _get_session(args)
    result = _send(
        session, "scroll", direction=args.direction, amount=args.amount
    )
    print(result["message"])


def cmd_upload(args: argparse.Namespace) -> None:
    session = _get_session(args)
    result = _send(session, "upload", selector=args.selector, file=args.file)
    print(result["message"])


def cmd_screenshot(args: argparse.Namespace) -> None:
    session = _get_session(args)
    result = _send(session, "screenshot", path=args.path)
    print(result["path"])


def cmd_eval(args: argparse.Namespace) -> None:
    session = _get_session(args)
    result = _send(session, "eval", expression=args.js)
    print(result["value"])


def cmd_get(args: argparse.Namespace) -> None:
    session = _get_session(args)
    result = _send(session, "get", what=args.what, selector=args.selector)
    print(result["value"])


def cmd_close(args: argparse.Namespace) -> None:
    session = _get_session(args)
    if not is_daemon_running(session):
        print("no daemon running")
        return
    try:
        _send(session, "close")
    except SystemExit:
        pass  # Daemon shuts down, connection may reset
    print("browser closed")


def cmd_cookie_refresh(args: argparse.Namespace) -> None:
    session = _get_session(args)
    site = args.site
    if not site:
        error("--site required for cookie refresh")
    result = _send(session, "cookie_refresh", site=site)
    print(result["message"])


def cmd_status(args: argparse.Namespace) -> None:
    session = _get_session(args)
    if not is_daemon_running(session):
        print("daemon: not running")
        return
    result = _send(session, "status")
    print(f"daemon: running")
    print(f"browser: {'connected' if result.get('browser_connected') else 'disconnected'}")
    print(f"mode: {'headed' if result.get('headed') else 'headless'}")
    if result.get("current_url"):
        print(f"url: {result['current_url']}")
    if result.get("current_site"):
        print(f"site: {result['current_site']}")


def _get_session(args: argparse.Namespace) -> str:
    """Determine which session/daemon to talk to."""
    if hasattr(args, "site") and args.site:
        return args.site
    # Try to find any running session
    from .utils import STATE_DIR
    if STATE_DIR.exists():
        for f in STATE_DIR.glob("*.pid"):
            return f.stem
    error("no active session. Run 'stealth-browser open <url>' first.")
    return ""  # unreachable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stealth-browser",
        description="Anti-detection browser automation CLI for AI agents",
    )
    parser.add_argument(
        "--headed", action="store_true", help="Run browser in headed mode (visible window)"
    )
    parser.add_argument(
        "--site", type=str, default=None, help="Site name for session/cookie partitioning"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Verbose output"
    )
    parser.add_argument(
        "--timeout", type=int, default=30000, help="Command timeout in ms"
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # open
    p_open = sub.add_parser("open", help="Navigate to a URL (auto-injects cookies)")
    p_open.add_argument("url", help="URL to navigate to")

    # snapshot
    p_snap = sub.add_parser("snapshot", help="Page text snapshot")
    p_snap.add_argument(
        "-i", "--interactive", action="store_true",
        help="Show interactive elements with indices"
    )

    # click
    p_click = sub.add_parser("click", help="Click an element")
    p_click.add_argument("selector", help="CSS selector")

    # fill
    p_fill = sub.add_parser("fill", help="Fill an input field")
    p_fill.add_argument("selector", help="CSS selector for the input")
    p_fill.add_argument("text", help="Text to type")

    # type
    p_type = sub.add_parser("type", help="Type text at current cursor position")
    p_type.add_argument("text", help="Text to type")

    # scroll
    p_scroll = sub.add_parser("scroll", help="Scroll the page")
    p_scroll.add_argument(
        "direction", choices=["up", "down"], help="Scroll direction"
    )
    p_scroll.add_argument(
        "amount", nargs="?", type=int, default=3, help="Number of scroll steps"
    )

    # upload
    p_upload = sub.add_parser("upload", help="Upload a file")
    p_upload.add_argument("selector", help="CSS selector for file input")
    p_upload.add_argument("file", help="Path to file")

    # screenshot
    p_ss = sub.add_parser("screenshot", help="Take a screenshot")
    p_ss.add_argument("path", nargs="?", default=None, help="Output file path")

    # eval
    p_eval = sub.add_parser("eval", help="Execute JavaScript")
    p_eval.add_argument("js", help="JavaScript expression")

    # get
    p_get = sub.add_parser("get", help="Get page information")
    p_get.add_argument(
        "what", choices=["text", "url", "title"], help="What to get"
    )
    p_get.add_argument("selector", nargs="?", default=None, help="CSS selector (for text)")

    # close
    sub.add_parser("close", help="Close browser and daemon")

    # cookie
    p_cookie = sub.add_parser("cookie", help="Cookie management")
    cookie_sub = p_cookie.add_subparsers(dest="cookie_cmd")
    cookie_sub.add_parser("refresh", help="Force re-extract cookies from Chrome")

    # status
    sub.add_parser("status", help="Show daemon status")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "open": cmd_open,
        "snapshot": cmd_snapshot,
        "click": cmd_click,
        "fill": cmd_fill,
        "type": cmd_type,
        "scroll": cmd_scroll,
        "upload": cmd_upload,
        "screenshot": cmd_screenshot,
        "eval": cmd_eval,
        "get": cmd_get,
        "close": cmd_close,
        "cookie": cmd_cookie_refresh,
        "status": cmd_status,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
