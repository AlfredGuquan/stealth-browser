"""Shared utilities for stealth-browser."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

# Base directory for all stealth-browser state files
STATE_DIR = Path.home() / ".stealth-browser"
SESSIONS_DIR = STATE_DIR / "sessions"

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


def error(msg: str, exit_code: int = 1) -> NoReturn:
    """Print error to stderr and exit."""
    print(f"error: {msg}", file=sys.stderr)
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
