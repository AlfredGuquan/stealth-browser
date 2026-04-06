"""Unit tests for stealth_browser.cli."""

import pytest
from stealth_browser.cli import build_parser, _site_from_url


class TestSiteFromUrl:
    def test_basic(self):
        assert _site_from_url("https://x.com/home") == "x.com"

    def test_strips_www(self):
        assert _site_from_url("https://www.example.com/page") == "example.com"

    def test_subdomain(self):
        assert _site_from_url("https://creator.xiaohongshu.com") == "creator.xiaohongshu.com"

    def test_with_port(self):
        assert _site_from_url("http://localhost:3000/") == "localhost"


class TestParser:
    def test_open(self):
        parser = build_parser()
        args = parser.parse_args(["open", "https://example.com"])
        assert args.command == "open"
        assert args.url == "https://example.com"

    def test_snapshot(self):
        parser = build_parser()
        args = parser.parse_args(["snapshot", "-i"])
        assert args.command == "snapshot"
        assert args.interactive is True

    def test_click(self):
        parser = build_parser()
        args = parser.parse_args(["click", "#button"])
        assert args.command == "click"
        assert args.selector == "#button"

    def test_fill(self):
        parser = build_parser()
        args = parser.parse_args(["fill", "#input", "hello world"])
        assert args.command == "fill"
        assert args.selector == "#input"
        assert args.text == "hello world"

    def test_scroll(self):
        parser = build_parser()
        args = parser.parse_args(["scroll", "down", "5"])
        assert args.command == "scroll"
        assert args.direction == "down"
        assert args.amount == 5

    def test_scroll_default_amount(self):
        parser = build_parser()
        args = parser.parse_args(["scroll", "up"])
        assert args.amount == 3

    def test_screenshot_no_path(self):
        parser = build_parser()
        args = parser.parse_args(["screenshot"])
        assert args.command == "screenshot"
        assert args.path is None

    def test_screenshot_with_path(self):
        parser = build_parser()
        args = parser.parse_args(["screenshot", "/tmp/shot.png"])
        assert args.path == "/tmp/shot.png"

    def test_eval(self):
        parser = build_parser()
        args = parser.parse_args(["eval", "document.title"])
        assert args.command == "eval"
        assert args.js == "document.title"

    def test_get(self):
        parser = build_parser()
        args = parser.parse_args(["get", "title"])
        assert args.command == "get"
        assert args.what == "title"
        assert args.selector is None

    def test_get_with_selector(self):
        parser = build_parser()
        args = parser.parse_args(["get", "text", "#content"])
        assert args.what == "text"
        assert args.selector == "#content"

    def test_global_options(self):
        parser = build_parser()
        args = parser.parse_args(["--headed", "--site", "x.com", "--verbose", "open", "https://x.com"])
        assert args.headed is True
        assert args.site == "x.com"
        assert args.verbose is True

    def test_close(self):
        parser = build_parser()
        args = parser.parse_args(["close"])
        assert args.command == "close"

    def test_status(self):
        parser = build_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_type(self):
        parser = build_parser()
        args = parser.parse_args(["type", "hello"])
        assert args.command == "type"
        assert args.text == "hello"

    def test_upload(self):
        parser = build_parser()
        args = parser.parse_args(["upload", "input[type=file]", "/tmp/photo.jpg"])
        assert args.command == "upload"
        assert args.selector == "input[type=file]"
        assert args.file == "/tmp/photo.jpg"
