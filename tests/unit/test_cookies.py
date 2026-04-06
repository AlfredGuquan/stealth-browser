"""Unit tests for stealth_browser.cookies."""

import json
import time
from dataclasses import dataclass
from unittest.mock import patch

import pytest
from stealth_browser.cookies import (
    _convert_pycookiecheat_to_playwright,
    clear_cache,
    load_cached,
    save_cache,
)


@dataclass
class MockCookie:
    """Mimics pycookiecheat.common.Cookie for testing."""
    name: str
    value: str
    host_key: str
    path: str
    expires_utc: int
    is_secure: bool


class TestConvertCookies:
    def test_basic_conversion(self):
        cookie = MockCookie(
            name="session_id",
            value="abc123",
            host_key=".example.com",
            path="/",
            # Chrome timestamp: 2025-01-01 00:00:00 UTC
            # = (1735689600 + 11644473600) * 1_000_000
            expires_utc=13380163200_000_000,
            is_secure=True,
        )
        result = _convert_pycookiecheat_to_playwright([cookie])
        assert len(result) == 1

        c = result[0]
        assert c["name"] == "session_id"
        assert c["value"] == "abc123"
        assert c["domain"] == ".example.com"
        assert c["path"] == "/"
        assert c["secure"] is True
        assert c["httpOnly"] is False
        assert c["sameSite"] == "Lax"
        # Verify epoch conversion: (13380163200_000_000 / 1e6) - 11644473600 = 1735689600
        assert c["expires"] == 1735689600

    def test_session_cookie_no_expiry(self):
        cookie = MockCookie(
            name="temp",
            value="xyz",
            host_key=".example.com",
            path="/",
            expires_utc=0,
            is_secure=False,
        )
        result = _convert_pycookiecheat_to_playwright([cookie])
        assert result[0]["expires"] == -1

    def test_multiple_cookies(self):
        cookies = [
            MockCookie("a", "1", ".x.com", "/", 13380163200_000_000, True),
            MockCookie("b", "2", ".x.com", "/api", 13380163200_000_000, False),
        ]
        result = _convert_pycookiecheat_to_playwright(cookies)
        assert len(result) == 2
        assert result[0]["name"] == "a"
        assert result[1]["name"] == "b"
        assert result[1]["path"] == "/api"
        assert result[1]["secure"] is False


class TestCacheOperations:
    @pytest.fixture
    def mock_dirs(self, tmp_path):
        """Redirect cache operations to a temp directory."""
        sessions = tmp_path / "sessions"
        sessions.mkdir()
        with (
            patch("stealth_browser.cookies.SESSIONS_DIR", sessions),
            patch("stealth_browser.cookies.STATE_DIR", tmp_path),
            patch("stealth_browser.cookies._cache_path", lambda site: sessions / f"{site}.json"),
        ):
            yield sessions

    def test_save_and_load(self, mock_dirs):
        cookies = [{"name": "test", "value": "123", "domain": ".example.com"}]
        save_cache("example.com", cookies)
        loaded = load_cached("example.com")
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0]["name"] == "test"

    def test_load_nonexistent(self, mock_dirs):
        result = load_cached("nonexistent.com")
        assert result is None

    def test_expired_cache(self, mock_dirs):
        cookies = [{"name": "old", "value": "stale"}]
        save_cache("expired.com", cookies)
        # Tamper with the cached_at to be in the past
        from stealth_browser.cookies import _cache_path, _decrypt, _encrypt
        path = mock_dirs / "expired.com.json"
        encrypted = path.read_bytes()
        raw = _decrypt(encrypted)
        data = json.loads(raw)
        data["cached_at"] = time.time() - 100000  # Way past TTL
        path.write_bytes(_encrypt(json.dumps(data)))

        result = load_cached("expired.com")
        assert result is None

    def test_clear_cache(self, mock_dirs):
        save_cache("clearme.com", [{"name": "x"}])
        assert (mock_dirs / "clearme.com.json").exists()
        clear_cache("clearme.com")
        assert not (mock_dirs / "clearme.com.json").exists()

    def test_clear_nonexistent(self, mock_dirs):
        # Should not raise
        clear_cache("nope.com")
