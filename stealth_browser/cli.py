"""CLI interface for stealth-browser.

Designed for AI agent consumption: plain text to stdout, errors to stderr,
non-zero exit codes on failure.

Invoked as `stealth-browser <command> [args]` or `python -m stealth_browser <command>`.

V2 additions:
- tab list/create/switch/close (F11)
- wait element/text/network-idle/<ms> (F7)
- dialog accept/dismiss/info (F8)
- back, forward, reload (F9)
- select, check, uncheck (F10)
- batch (F13)
- Snapshot refs: click/fill/select/check accept @eN refs (F6)
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.parse import urlparse

from .daemon import is_daemon_running, send_command, start_daemon
from .utils import EXIT_AUTH_EXPIRED, EXIT_RUNTIME, EXIT_USAGE, error, is_local_dev_url


def _site_from_url(url: str) -> str:
    """Extract a site name from a URL for session/cache partitioning."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _ensure_daemon(
    session: str, headed: bool, extensions: list[str] | None = None
) -> None:
    """Start the daemon if not already running.

    Extensions imply headed (Chrome requirement); we auto-upgrade rather than error.
    """
    if extensions and not headed:
        headed = True
    if not is_daemon_running(session):
        try:
            start_daemon(session, headed=headed, extensions=extensions)
        except RuntimeError as e:
            error(
                f"failed to start daemon: {e}",
                code="DAEMON_FAILED",
                retryable=True,
                fix="retry; check ~/.stealth-browser/*.log",
            )


def _send(session: str, command: str, **kwargs) -> dict:
    """Send a command to the daemon and return the result. Exit on error."""
    try:
        result = send_command(session, command, **kwargs)
    except RuntimeError as e:
        error(
            str(e),
            code="DAEMON_FAILED",
            retryable=True,
            fix="retry; daemon may have crashed (check ~/.stealth-browser/*.log)",
        )
    except Exception as e:
        error(
            f"communication error: {e}",
            code="DAEMON_FAILED",
            retryable=True,
            fix="retry; daemon may have crashed",
        )

    if result.get("status") == "error":
        # Map AUTH_EXPIRED to exit 5, USAGE/INVALID_INPUT to exit 2, else 1.
        code = result.get("code", "UNKNOWN")
        if code == "AUTH_EXPIRED":
            exit_code = EXIT_AUTH_EXPIRED
        elif code in ("USAGE", "INVALID_INPUT"):
            exit_code = EXIT_USAGE
        else:
            exit_code = EXIT_RUNTIME
        error(
            result.get("error", "unknown error"),
            exit_code=exit_code,
            code=code,
            retryable=result.get("retryable", True),
            fix=result.get("fix", "see `--help`"),
        )

    return result


def cmd_open(args: argparse.Namespace) -> None:
    url = args.url
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    site = args.site or _site_from_url(url)
    session = site

    # F14: skip cookies and login_redirect detection for local dev URLs
    # or when --no-cookie is explicitly set.
    skip_cookies = bool(getattr(args, "no_cookie", False)) or is_local_dev_url(url)

    _ensure_daemon(session, args.headed, getattr(args, "extensions", None))
    result = _send(
        session,
        "open",
        url=url,
        site=site,
        timeout=args.timeout,
        skip_cookies=skip_cookies,
    )

    if result.get("login_redirect"):
        # Failure path: stderr only. Don't print URL/Title to stdout --
        # agents may misread stdout as success (status.md F5).
        error(
            f"session expired for {site}",
            exit_code=EXIT_AUTH_EXPIRED,
            code="AUTH_EXPIRED",
            retryable=False,
            fix=f"log in to {site} in Chrome, then retry",
        )

    print(f"URL: {result['url']}")
    print(f"Title: {result['title']}")


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
    visible = (result.get("visible_text") or "").strip()
    if visible:
        print("---")
        print(visible)


def cmd_upload(args: argparse.Namespace) -> None:
    session = _get_session(args)
    result = _send(session, "upload", selector=args.selector, file=args.file)
    print(result["message"])


def cmd_assert(args: argparse.Namespace) -> None:
    """assert text/element — PASS prints to stdout, FAIL surfaces via _send (exit 1)."""
    session = _get_session(args)
    # On FAIL, daemon returns status=error code=ASSERTION_FAILED; _send exits.
    result = _send(session, "assert", kind=args.kind, target=args.target)
    print(result["message"])


def cmd_screenshot(args: argparse.Namespace) -> None:
    session = _get_session(args)
    annotate = bool(getattr(args, "annotate", False))
    result = _send(
        session, "screenshot", path=args.path, annotate=annotate
    )
    # Line 1: file path (unchanged contract for existing agents).
    print(result["path"])
    if annotate:
        # Legend: [N] @eN <tag> "text"
        for i, item in enumerate(result.get("legend", []), start=1):
            text = item.get("text", "") or ""
            print(f'[{i}] {item["ref"]} <{item["tag"]}> "{text}"')


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
        pass
    print("browser closed")


def cmd_cookie_refresh(args: argparse.Namespace) -> None:
    session = _get_session(args)
    site = args.site
    if not site:
        error(
            "--site required for cookie refresh",
            exit_code=EXIT_USAGE,
            code="USAGE",
            retryable=False,
            fix="pass --site <name>",
        )
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
    print(f"active tab: {result.get('active_tab', 0)}")
    print(f"tab count: {result.get('tab_count', 1)}")


# -- F10: Select/Check --

def cmd_select(args: argparse.Namespace) -> None:
    session = _get_session(args)
    result = _send(session, "select", selector=args.selector, value=args.value)
    print(result["message"])


def cmd_check(args: argparse.Namespace) -> None:
    session = _get_session(args)
    result = _send(session, "check", selector=args.selector)
    print(result["message"])


def cmd_uncheck(args: argparse.Namespace) -> None:
    session = _get_session(args)
    result = _send(session, "uncheck", selector=args.selector)
    print(result["message"])


# -- F7: Wait --

def cmd_wait(args: argparse.Namespace) -> None:
    session = _get_session(args)
    wait_type = args.wait_type
    target = args.target
    timeout = args.timeout

    if wait_type == "network-idle":
        result = _send(session, "wait", type="network-idle", target="", timeout=timeout)
    elif wait_type.isdigit():
        # `wait 5000` -- wait for N ms
        result = _send(session, "wait", type="timeout", target=wait_type)
    elif wait_type == "url":
        # F15: wait url <glob-pattern>
        if not target:
            error(
                "wait url: pattern required (e.g. 'wait url \"**/success\"')",
                exit_code=EXIT_USAGE,
                code="USAGE",
                retryable=False,
                fix='pass a glob pattern, e.g. wait url "**/dashboard"',
            )
        result = _send(
            session, "wait", type="url", target=target, timeout=timeout
        )
    else:
        # wait element <selector|ref> or wait text <text>
        result = _send(
            session, "wait", type=wait_type, target=target, timeout=timeout
        )
    print(result["message"])


# -- F8: Dialog --

def cmd_dialog(args: argparse.Namespace) -> None:
    session = _get_session(args)
    action = args.dialog_action

    if action is None:
        print("usage: stealth-browser dialog {accept,dismiss,info,auto-dismiss}")
        print("\nsubcommands:")
        print("  accept          Accept the dialog (optional text for prompts)")
        print("  dismiss         Dismiss the dialog")
        print("  info            Show dialog info")
        print("  auto-dismiss    Toggle auto-dismiss mode (on/off)")
        sys.exit(0)

    if action == "accept":
        text = getattr(args, "text", None)
        kwargs = {"action": "accept"}
        if text:
            kwargs["text"] = text
        result = _send(session, "dialog", **kwargs)
        print(result["message"])
    elif action == "dismiss":
        result = _send(session, "dialog", action="dismiss")
        print(result["message"])
    elif action == "info":
        result = _send(session, "dialog", action="info")
        if result.get("present"):
            print(f"type: {result['type']}")
            print(f"message: {result['message']}")
            if result.get("default_value"):
                print(f"default: {result['default_value']}")
            print(f"handled: {result['handled']}")
        else:
            print("no dialog present")
    elif action == "auto-dismiss":
        mode = getattr(args, "mode", "on")
        enabled = mode != "off"
        result = _send(session, "dialog", action="auto-dismiss", enabled=enabled)
        print(result["message"])
    else:
        error(
            f"unknown dialog action: {action}",
            exit_code=EXIT_USAGE,
            code="USAGE",
            retryable=False,
            fix="use one of: accept, dismiss, info, auto-dismiss",
        )


# -- F9: Navigation --

def cmd_back(args: argparse.Namespace) -> None:
    session = _get_session(args)
    result = _send(session, "back")
    print(f"URL: {result['url']}")
    print(f"Title: {result['title']}")


def cmd_forward(args: argparse.Namespace) -> None:
    session = _get_session(args)
    result = _send(session, "forward")
    print(f"URL: {result['url']}")
    print(f"Title: {result['title']}")


def cmd_reload(args: argparse.Namespace) -> None:
    session = _get_session(args)
    result = _send(session, "reload")
    print(f"URL: {result['url']}")
    print(f"Title: {result['title']}")


# -- F11: Multi-tab --

def cmd_tab(args: argparse.Namespace) -> None:
    session = _get_session(args)
    action = args.tab_action

    if action is None:
        print("usage: stealth-browser tab {list,create,switch,close}")
        print("\nsubcommands:")
        print("  list            List open tabs")
        print("  create [url]    Create a new tab")
        print("  switch <id>     Switch to a tab")
        print("  close [id]      Close a tab (default: active)")
        sys.exit(0)

    if action == "list":
        result = _send(session, "tab", action="list")
        for tab in result["tabs"]:
            marker = "*" if tab["active"] else " "
            title = tab.get("title", "")
            print(f"  {marker} [{tab['tab_id']}] {tab['url']} - {title}")

    elif action == "create":
        url = getattr(args, "url", None)
        kwargs: dict[str, Any] = {"action": "create"}
        if url:
            kwargs["url"] = url
        result = _send(session, "tab", **kwargs)
        print(f"tab {result['tab_id']} created")
        if result.get("url"):
            print(f"URL: {result['url']}")

    elif action == "switch":
        tab_id = args.tab_id
        result = _send(session, "tab", action="switch", tab_id=tab_id)
        print(result["message"])

    elif action == "close":
        tab_id = getattr(args, "tab_id", None)
        kwargs = {"action": "close"}
        if tab_id is not None:
            kwargs["tab_id"] = tab_id
        result = _send(session, "tab", **kwargs)
        print(result["message"])

    else:
        error(
            f"unknown tab action: {action}",
            exit_code=EXIT_USAGE,
            code="USAGE",
            retryable=False,
            fix="use one of: list, create, switch, close",
        )


# -- F13: Batch --

def cmd_batch(args: argparse.Namespace) -> None:
    session = _get_session(args)

    # Read commands from stdin
    raw = sys.stdin.read()
    try:
        commands = json.loads(raw)
    except json.JSONDecodeError as e:
        error(
            f"invalid JSON from stdin: {e}",
            exit_code=EXIT_USAGE,
            code="INVALID_INPUT",
            retryable=False,
            fix="check JSON syntax in batch input",
        )

    if not isinstance(commands, list):
        error(
            "batch expects a JSON array of command objects",
            exit_code=EXIT_USAGE,
            code="INVALID_INPUT",
            retryable=False,
            fix="wrap commands in [...] (top-level must be an array)",
        )

    # Bypass _send() -- batch returns structured partial results on error,
    # and _send() would sys.exit(1) before we can display them.
    timeout_per_cmd = args.timeout / 1000  # ms -> seconds
    total_timeout = max(timeout_per_cmd * len(commands), 60)
    try:
        result = send_command(
            session, "batch", timeout=total_timeout,
            commands=commands, fast=args.fast,
        )
    except RuntimeError as e:
        error(
            str(e),
            code="DAEMON_FAILED",
            retryable=True,
            fix="retry; daemon may have crashed",
        )
    except Exception as e:
        error(
            f"communication error: {e}",
            code="DAEMON_FAILED",
            retryable=True,
            fix="retry; daemon may have crashed",
        )

    if result["status"] == "ok":
        print(f"batch: {len(result['results'])} commands completed")
        for i, r in enumerate(result["results"]):
            status = r.get("status", "?")
            msg = r.get("message", r.get("content", r.get("value", r.get("path", ""))))
            print(f"  [{i}] {status}: {msg}")
    else:
        # Partial-failure path: show completed-count on stderr too (no stdout
        # writes -- agents must not see partial-success on stdout).
        completed = result.get("completed", [])
        print(
            f"batch: failed at command {result.get('failed_index', '?')} "
            f"({len(completed)} completed before failure)",
            file=sys.stderr,
        )
        code = result.get("code", "RUNTIME")
        if code == "AUTH_EXPIRED":
            exit_code = EXIT_AUTH_EXPIRED
        elif code in ("USAGE", "INVALID_INPUT"):
            exit_code = EXIT_USAGE
        else:
            exit_code = EXIT_RUNTIME
        error(
            result.get("error", "unknown"),
            exit_code=exit_code,
            code=code,
            retryable=result.get("retryable", True),
            fix=result.get("fix", "see `--help`"),
        )


# -- Network recording --

def _format_network_entry(entry: dict, t0: float) -> str:
    """Format one network log entry as a single line."""
    elapsed = entry["timestamp"] - t0
    method = entry.get("method", "?")
    status = entry.get("status") or "..."
    rtype = entry.get("resource_type", "?")
    url = entry.get("url", "")
    # Truncate long URLs for readability
    if len(url) > 120:
        url = url[:117] + "..."
    return f"[{elapsed:6.1f}s] {method:<4} {status:<3}  {rtype:<12} {url}"


def cmd_network(args: argparse.Namespace) -> None:
    session = _get_session(args)
    action = args.network_action

    if action is None:
        print("usage: stealth-browser network {start,stop,list,clear}")
        print("\nsubcommands:")
        print("  start                Start recording (mark current position)")
        print("  stop  [--types ...]  Stop recording, show new requests since start")
        print("  list  [--types ...]  Show all buffered requests")
        print("  clear                Clear the network log")
        print("\n--types filters by resource type (xhr, fetch, document, stylesheet,")
        print("  image, font, script, media, websocket, etc.). Omit for all types.")
        sys.exit(0)

    types = getattr(args, "types", None) or None

    if action == "start":
        result = _send(session, "network", action="start")
        print(result["message"])

    elif action == "stop":
        result = _send(session, "network", action="stop", types=types)
        entries = result.get("entries", [])
        total = result.get("total", 0)
        shown = result.get("shown", 0)

        if result.get("note"):
            print(result["note"])
            return

        if not entries:
            print("no requests captured")
            return

        t0 = entries[0]["timestamp"]
        print(f"Network requests ({shown} shown, {total} total):\n")
        for e in entries:
            print(_format_network_entry(e, t0))

    elif action == "list":
        result = _send(session, "network", action="list", types=types)
        entries = result.get("entries", [])
        total = result.get("total", 0)
        shown = result.get("shown", 0)

        if not entries:
            print("network log empty")
            return

        t0 = entries[0]["timestamp"]
        print(f"Network requests ({shown} shown, {total} total):\n")
        for e in entries:
            print(_format_network_entry(e, t0))

    elif action == "clear":
        result = _send(session, "network", action="clear")
        print(result["message"])

    else:
        error(
            f"unknown network action: {action}",
            exit_code=EXIT_USAGE,
            code="USAGE",
            retryable=False,
            fix="use one of: start, stop, list, clear",
        )


def _get_session(args: argparse.Namespace) -> str:
    """Determine which session/daemon to talk to."""
    if hasattr(args, "site") and args.site:
        return args.site
    from .utils import STATE_DIR
    if STATE_DIR.exists():
        for f in STATE_DIR.glob("*.pid"):
            return f.stem
    error(
        "no active session. Run 'stealth-browser open <url>' first.",
        code="NO_SESSION",
        retryable=False,
        fix="run `stealth-browser open <url>` to start a session",
    )


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
    parser.add_argument(
        "--no-cookie",
        action="store_true",
        dest="no_cookie",
        help="Skip cookie injection and login_redirect detection (F14). "
             "Useful for local dev URLs or sites where cookies aren't needed.",
    )
    parser.add_argument(
        "--extension",
        action="append",
        dest="extensions",
        default=None,
        metavar="PATH",
        help="Load an unpacked Chrome extension (repeatable). "
             "Implies --headed. Forks a separate persistent profile under "
             "~/.stealth-browser/ext-profile/.",
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # open
    p_open = sub.add_parser("open", help="Navigate to a URL (auto-injects cookies)")
    p_open.add_argument("url", help="URL to navigate to")

    # snapshot
    p_snap = sub.add_parser("snapshot", help="Page text snapshot")
    p_snap.add_argument(
        "-i", "--interactive", action="store_true",
        help="Show interactive elements with @eN refs"
    )

    # click (accepts @eN ref or CSS selector)
    p_click = sub.add_parser("click", help="Click an element (@eN ref or CSS selector)")
    p_click.add_argument("selector", help="@eN ref or CSS selector")

    # fill (accepts @eN ref or CSS selector)
    p_fill = sub.add_parser("fill", help="Fill an input field")
    p_fill.add_argument("selector", help="@eN ref or CSS selector for the input")
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
    p_upload.add_argument("selector", help="@eN ref or CSS selector for file input")
    p_upload.add_argument("file", help="Path to file")

    # screenshot
    p_ss = sub.add_parser("screenshot", help="Take a screenshot")
    p_ss.add_argument("path", nargs="?", default=None, help="Output file path")
    p_ss.add_argument(
        "--annotate",
        action="store_true",
        help="Overlay numeric labels on @eN refs from the last snapshot "
             "(F16). Requires a prior `snapshot -i`.",
    )

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

    # -- F10: Select/Check --

    p_select = sub.add_parser("select", help="Select an option from a <select> element")
    p_select.add_argument("selector", help="@eN ref or CSS selector")
    p_select.add_argument("value", help="Value to select")

    p_check = sub.add_parser("check", help="Check a checkbox or radio button")
    p_check.add_argument("selector", help="@eN ref or CSS selector")

    p_uncheck = sub.add_parser("uncheck", help="Uncheck a checkbox")
    p_uncheck.add_argument("selector", help="@eN ref or CSS selector")

    # -- F7: Wait --

    p_wait = sub.add_parser("wait", help="Wait for condition")
    p_wait.add_argument(
        "wait_type",
        help="element, text, url, network-idle, or milliseconds (e.g. 5000)"
    )
    p_wait.add_argument(
        "target", nargs="?", default="",
        help="@eN ref/CSS selector (for element), text string (for text), "
             "or URL glob pattern (for url)"
    )

    # assert text/element — structured PASS/FAIL (exit 1 with code:ASSERTION_FAILED on miss)
    p_assert = sub.add_parser(
        "assert", help="Assert text or element is present (PASS/FAIL with structured exit)"
    )
    p_assert.add_argument(
        "kind", choices=["text", "element"], help="What to assert"
    )
    p_assert.add_argument(
        "target", help="Text string (for text) or @eN ref/CSS selector (for element)"
    )

    # -- F8: Dialog --

    p_dialog = sub.add_parser("dialog", help="Handle browser dialogs (alert/confirm/prompt)")
    dialog_sub = p_dialog.add_subparsers(dest="dialog_action")
    p_dialog_accept = dialog_sub.add_parser("accept", help="Accept the dialog")
    p_dialog_accept.add_argument("text", nargs="?", default=None, help="Text for prompt dialog")
    dialog_sub.add_parser("dismiss", help="Dismiss the dialog")
    dialog_sub.add_parser("info", help="Show dialog info")
    p_dialog_auto = dialog_sub.add_parser("auto-dismiss", help="Toggle auto-dismiss mode")
    p_dialog_auto.add_argument(
        "mode", nargs="?", default="on", choices=["on", "off"],
        help="on (default) or off"
    )

    # -- F9: Navigation --

    sub.add_parser("back", help="Navigate back")
    sub.add_parser("forward", help="Navigate forward")
    sub.add_parser("reload", help="Reload current page")

    # -- F11: Multi-tab --

    p_tab = sub.add_parser("tab", help="Tab management")
    tab_sub = p_tab.add_subparsers(dest="tab_action")
    tab_sub.add_parser("list", help="List open tabs")
    p_tab_create = tab_sub.add_parser("create", help="Create a new tab")
    p_tab_create.add_argument("url", nargs="?", default=None, help="URL to open in new tab")
    p_tab_switch = tab_sub.add_parser("switch", help="Switch to a tab")
    p_tab_switch.add_argument("tab_id", type=int, help="Tab ID to switch to")
    p_tab_close = tab_sub.add_parser("close", help="Close a tab")
    p_tab_close.add_argument("tab_id", nargs="?", type=int, default=None, help="Tab ID (default: active)")

    # -- Network recording --

    p_net = sub.add_parser("network", help="Network request recording and discovery")
    net_sub = p_net.add_subparsers(dest="network_action")
    net_sub.add_parser("start", help="Start recording (mark current position)")
    p_net_stop = net_sub.add_parser("stop", help="Stop recording, show new requests")
    p_net_stop.add_argument(
        "--types", nargs="+", metavar="TYPE",
        help="Filter by resource type (xhr, fetch, document, stylesheet, image, font, script, media, websocket, ...)",
    )
    p_net_list = net_sub.add_parser("list", help="Show all buffered requests")
    p_net_list.add_argument(
        "--types", nargs="+", metavar="TYPE",
        help="Filter by resource type",
    )
    net_sub.add_parser("clear", help="Clear the network log")

    # -- F13: Batch --

    p_batch = sub.add_parser("batch", help="Execute commands from stdin JSON array")
    p_batch.add_argument(
        "--fast", action="store_true",
        help="Skip cognitive gap delays between commands"
    )

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
        # V2
        "select": cmd_select,
        "check": cmd_check,
        "uncheck": cmd_uncheck,
        "wait": cmd_wait,
        "assert": cmd_assert,
        "dialog": cmd_dialog,
        "back": cmd_back,
        "forward": cmd_forward,
        "reload": cmd_reload,
        "tab": cmd_tab,
        "network": cmd_network,
        "batch": cmd_batch,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
