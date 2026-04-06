"""Unit tests for stealth_browser.utils."""

import pytest
from stealth_browser.utils import (
    STATE_DIR,
    SESSIONS_DIR,
    ensure_dirs,
    get_chrome_ua,
    is_login_redirect,
    socket_path,
    pid_path,
)


class TestIsLoginRedirect:
    def test_login_paths(self):
        assert is_login_redirect("https://x.com/login") is True
        assert is_login_redirect("https://x.com/i/flow/login") is True
        assert is_login_redirect("https://accounts.google.com/signin") is True
        assert is_login_redirect("https://example.com/auth/callback") is True
        assert is_login_redirect("https://example.com/sso") is True
        assert is_login_redirect("https://example.com/oauth/authorize") is True

    def test_non_login_paths(self):
        assert is_login_redirect("https://x.com/home") is False
        assert is_login_redirect("https://example.com/") is False
        assert is_login_redirect("https://example.com/dashboard") is False
        assert is_login_redirect("https://example.com/blog/login-tips") is False

    def test_case_insensitive(self):
        assert is_login_redirect("https://example.com/Login") is True
        assert is_login_redirect("https://example.com/SIGNIN") is True


class TestGetChromeUA:
    def test_returns_string(self):
        ua = get_chrome_ua()
        assert isinstance(ua, str)
        assert "Chrome" in ua
        assert "Mozilla/5.0" in ua

    def test_no_headless_marker(self):
        ua = get_chrome_ua()
        assert "HeadlessChrome" not in ua


class TestPaths:
    def test_state_dir(self):
        assert STATE_DIR.name == ".stealth-browser"

    def test_sessions_dir(self):
        assert SESSIONS_DIR.parent == STATE_DIR
        assert SESSIONS_DIR.name == "sessions"

    def test_socket_path(self):
        p = socket_path("test-session")
        assert p.name == "test-session.sock"
        assert p.parent == STATE_DIR

    def test_pid_path(self):
        p = pid_path("test-session")
        assert p.name == "test-session.pid"
        assert p.parent == STATE_DIR

    def test_ensure_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setattr("stealth_browser.utils.STATE_DIR", tmp_path / ".sb")
        monkeypatch.setattr("stealth_browser.utils.SESSIONS_DIR", tmp_path / ".sb" / "sessions")
        from stealth_browser import utils
        utils.STATE_DIR = tmp_path / ".sb"
        utils.SESSIONS_DIR = tmp_path / ".sb" / "sessions"
        ensure_dirs()
        assert (tmp_path / ".sb").exists()
        assert (tmp_path / ".sb" / "sessions").exists()
