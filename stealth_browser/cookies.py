"""Cookie extraction, conversion, caching, and expiry detection.

Flow:
1. Check session cache file (~/.stealth-browser/sessions/{site}.json)
2. Cache hit + not expired -> load and return
3. Cache miss or expired -> pycookiecheat from Chrome -> convert -> cache -> return
4. After navigation, caller checks for login redirect (session expiry)

pycookiecheat with as_cookies=True returns pycookiecheat.common.Cookie dataclass:
  - host_key (not domain)
  - expires_utc (Chrome microseconds since 1601-01-01, not Unix epoch)
  - is_secure (not secure)
  - no httpOnly field
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from .utils import SESSIONS_DIR, STATE_DIR, ensure_dirs, warn

# Cache validity: 24 hours by default
CACHE_TTL_SECONDS = 86400


def _get_encryption_key() -> bytes:
    """Get or create the Fernet encryption key.

    Key source priority:
    1. AGENT_BROWSER_ENCRYPTION_KEY environment variable
    2. Auto-generated key stored in ~/.stealth-browser/key
    """
    env_key = os.environ.get("AGENT_BROWSER_ENCRYPTION_KEY")
    if env_key:
        return env_key.encode() if isinstance(env_key, str) else env_key

    key_path = STATE_DIR / "key"
    if key_path.exists():
        return key_path.read_bytes().strip()

    # Generate and persist a new key
    ensure_dirs()
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    return key


def _encrypt(data: str) -> bytes:
    f = Fernet(_get_encryption_key())
    return f.encrypt(data.encode())


def _decrypt(data: bytes) -> str:
    f = Fernet(_get_encryption_key())
    return f.decrypt(data).decode()


def _cache_path(site: str) -> Path:
    return SESSIONS_DIR / f"{site}.json"


def _convert_pycookiecheat_to_playwright(
    cookies: list[Any],
) -> list[dict[str, Any]]:
    """Convert pycookiecheat.common.Cookie objects to Playwright cookie dicts.

    Key conversions:
    - host_key -> domain
    - expires_utc (Chrome microseconds since 1601) -> expires (Unix seconds)
    - is_secure -> secure
    - httpOnly defaults to False (pycookiecheat doesn't expose it)
    """
    pw_cookies = []
    for c in cookies:
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
                "httpOnly": False,
                "secure": bool(c.is_secure),
                "sameSite": "Lax",
            }
        )
    return pw_cookies


def extract_cookies(url: str) -> list[dict[str, Any]]:
    """Extract cookies from Chrome for the given URL and convert to Playwright format."""
    from pycookiecheat import BrowserType, get_cookies

    raw = get_cookies(url, browser=BrowserType.CHROME, as_cookies=True)
    return _convert_pycookiecheat_to_playwright(raw)


def load_cached(site: str) -> list[dict[str, Any]] | None:
    """Load cached cookies for a site. Returns None if no cache or expired."""
    ensure_dirs()
    path = _cache_path(site)
    if not path.exists():
        return None

    try:
        encrypted = path.read_bytes()
        raw = _decrypt(encrypted)
        data = json.loads(raw)
    except Exception:
        warn(f"corrupt session cache for {site}, will re-extract")
        path.unlink(missing_ok=True)
        return None

    # Check TTL
    cached_at = data.get("cached_at", 0)
    if time.time() - cached_at > CACHE_TTL_SECONDS:
        return None

    return data.get("cookies", [])


def save_cache(site: str, cookies: list[dict[str, Any]]) -> None:
    """Encrypt and save cookies to the session cache file."""
    ensure_dirs()
    data = {"cached_at": time.time(), "cookies": cookies}
    encrypted = _encrypt(json.dumps(data))
    path = _cache_path(site)
    path.write_bytes(encrypted)
    path.chmod(0o600)


def clear_cache(site: str) -> None:
    """Remove the session cache for a site."""
    path = _cache_path(site)
    path.unlink(missing_ok=True)


def get_cookies_for_site(site: str, url: str) -> list[dict[str, Any]]:
    """Get cookies for a site: from cache if valid, otherwise extract from Chrome.

    Returns the Playwright-format cookie list.
    """
    cached = load_cached(site)
    if cached:
        return cached

    cookies = extract_cookies(url)
    if cookies:
        save_cache(site, cookies)
    return cookies
