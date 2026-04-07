"""F14 tracer: validate pycookiecheat behavior on localhost + hostname classifier.

Goal:
- Determine whether pycookiecheat raises / returns empty / returns Chrome cookies
  for http://localhost:3000. Decides whether F14 gating must be in cli/daemon
  (pre-call) or can live in cookies.py (catch branch).
- Sanity-check a hostname classifier function for the rules in PRD F14.
"""

from __future__ import annotations

import traceback
from urllib.parse import urlparse


def is_local_dev_url(url: str) -> bool:
    """Return True if URL points at local dev environment (skip cookie injection).

    Rules from PRD F14:
      hostname ∈ {localhost, 127.0.0.1, [::1], 0.0.0.0}
      hostname ends with .local
    Internal IP ranges (10.x, 172.16-31.x, 192.168.x) are NOT considered local.
    """
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    if not host:
        return False
    host = host.lower()
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return True
    if host.endswith(".local"):
        return True
    return False


def test_classifier() -> None:
    cases = [
        ("http://localhost:3000", True),
        ("http://localhost", True),
        ("http://127.0.0.1:8080", True),
        ("http://[::1]:5173", True),
        ("http://0.0.0.0:9000", True),
        ("http://myapp.local", True),
        ("http://myapp.local:4000/path", True),
        ("http://192.168.1.100", False),
        ("http://10.0.0.5:8080", False),
        ("http://172.16.5.1", False),
        ("http://172.20.0.1", False),
        ("https://example.com", False),
        ("https://creator.xiaohongshu.com", False),
        ("https://x.com", False),
    ]
    print("== hostname classifier ==")
    fail = 0
    for url, expected in cases:
        got = is_local_dev_url(url)
        status = "ok" if got == expected else "FAIL"
        if got != expected:
            fail += 1
        print(f"  {status:4} {url:50} expected={expected} got={got}")
    print(f"  classifier: {len(cases) - fail}/{len(cases)} passed")


def test_pycookiecheat_localhost() -> None:
    print("\n== pycookiecheat behavior on localhost ==")
    from pycookiecheat import BrowserType, get_cookies

    for url in (
        "http://localhost:3000",
        "http://127.0.0.1:8080",
        "http://example.local",
    ):
        print(f"\n  url={url}")
        try:
            raw = get_cookies(url, browser=BrowserType.CHROME, as_cookies=True)
            print(f"    type={type(raw).__name__}  len={len(raw) if hasattr(raw, '__len__') else 'n/a'}")
            if hasattr(raw, "__len__") and len(raw) > 0:
                print(f"    first={raw[0]!r}")
        except Exception as e:
            print(f"    raised {type(e).__name__}: {e}")
            traceback.print_exc()


if __name__ == "__main__":
    test_classifier()
    test_pycookiecheat_localhost()
