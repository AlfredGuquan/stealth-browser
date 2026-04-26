"""Shared utilities for stealth-browser."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlparse

# Base directory for all stealth-browser state files
STATE_DIR = Path.home() / ".stealth-browser"
SESSIONS_DIR = STATE_DIR / "sessions"

# F14: hostnames that count as local dev -- cookie injection and
# login_redirect detection are both skipped for these.
# Internal IPs (192.168.x, 10.x, 172.16-31.x) do NOT count as local dev.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})

# Default Chrome UA -- updated when we can detect the real version
DEFAULT_CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)

# Common login-page URL patterns -- match as full path segments (not substrings)
LOGIN_PATTERNS = re.compile(
    r"/(?:login|signin|sign-in|auth|sso|oauth|account/login)(?:[/?#]|$)", re.IGNORECASE
)


def ensure_dirs() -> None:
    """Create state directories if they don't exist."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def detect_chrome_version() -> str | None:
    """Return the installed Chrome version string, or None if not found."""
    if platform.system() != "Darwin":
        return None
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not os.path.exists(chrome_path):
        return None
    try:
        result = subprocess.run(
            [chrome_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # "Google Chrome 146.0.6794.0"
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)", result.stdout)
        return match.group(1) if match else None
    except Exception:
        return None


def get_chrome_ua() -> str:
    """Build a realistic Chrome UA string using the installed version."""
    version = detect_chrome_version()
    if version:
        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{version} Safari/537.36"
        )
    return DEFAULT_CHROME_UA


def is_login_redirect(url: str) -> bool:
    """Heuristic: does the URL look like a login/auth page?"""
    return bool(LOGIN_PATTERNS.search(url))


def is_local_dev_url(url: str) -> bool:
    """True if the URL targets a local dev host (F14).

    Matches localhost / 127.0.0.1 / ::1 / 0.0.0.0 / *.local hosts. Internal
    private IPs (192.168.x, 10.x, 172.16-31.x) deliberately do NOT match --
    they may still need site cookies.
    """
    host = (urlparse(url).hostname or "").lower()
    # Strip IPv6 brackets if urlparse kept them (hostname usually doesn't)
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host in LOCAL_HOSTS or host.endswith(".local")


# Exit code categories (status.md F5):
#   2 — usage / input shape errors (agent fix: change command)
#   5 — auth expired / cookie failed (agent fix: ask user to re-login)
#   1 — everything else (runtime, daemon, unknown)
EXIT_RUNTIME = 1
EXIT_USAGE = 2
EXIT_AUTH_EXPIRED = 5

# Known structured error codes -- free-form strings, not enforced.
# Agents key off these in stderr `code:` lines.
#   USAGE          — bad CLI args / unknown action / missing required flag
#   INVALID_INPUT  — batch JSON shape / schema errors
#   NO_SESSION     — no active session for this site
#   AUTH_EXPIRED   — login_redirect detected, cookies expired
#   DAEMON_FAILED  — daemon start / IPC failure
#   RUNTIME        — engine / browser runtime error (timeout, element missing)
#   UNKNOWN        — fallback


def error(
    msg: str,
    exit_code: int = EXIT_RUNTIME,
    *,
    code: str = "UNKNOWN",
    retryable: bool = True,
    fix: str = "see `--help`",
) -> NoReturn:
    """Print structured error to stderr and exit.

    Output is four lines, each `key: value`. Agents parse by line prefix
    (status.md F5 explicitly rules out JSON for error envelope).
    """
    print(f"error: {msg}", file=sys.stderr)
    print(f"code: {code}", file=sys.stderr)
    print(f"retryable: {'true' if retryable else 'false'}", file=sys.stderr)
    print(f"fix: {fix}", file=sys.stderr)
    sys.exit(exit_code)


def warn(msg: str) -> None:
    """Print warning to stderr."""
    print(f"warning: {msg}", file=sys.stderr)


_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def _validate_name(name: str) -> str:
    """Validate that a name contains only safe characters.

    Prevents path traversal via crafted session/site names like '../../etc/foo'.
    """
    if not name or not _SAFE_NAME_RE.match(name):
        raise ValueError(
            f"invalid name {name!r}: must match [a-zA-Z0-9._-]"
        )
    return name


def socket_path(session: str) -> Path:
    """Return the Unix domain socket path for a session."""
    return STATE_DIR / f"{_validate_name(session)}.sock"


def pid_path(session: str) -> Path:
    """Return the PID file path for a session."""
    return STATE_DIR / f"{_validate_name(session)}.pid"
