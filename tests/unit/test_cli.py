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

    def test_click_with_ref(self):
        parser = build_parser()
        args = parser.parse_args(["click", "@e5"])
        assert args.selector == "@e5"

    def test_fill(self):
        parser = build_parser()
        args = parser.parse_args(["fill", "#input", "hello world"])
        assert args.command == "fill"
        assert args.selector == "#input"
        assert args.text == "hello world"

    def test_fill_with_ref(self):
        parser = build_parser()
        args = parser.parse_args(["fill", "@e3", "text"])
        assert args.selector == "@e3"

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


class TestSelectCheckParser:
    """F10: select, check, uncheck parser tests."""

    def test_select(self):
        parser = build_parser()
        args = parser.parse_args(["select", "#dropdown", "option1"])
        assert args.command == "select"
        assert args.selector == "#dropdown"
        assert args.value == "option1"

    def test_select_with_ref(self):
        parser = build_parser()
        args = parser.parse_args(["select", "@e2", "val"])
        assert args.selector == "@e2"

    def test_check(self):
        parser = build_parser()
        args = parser.parse_args(["check", "#agree"])
        assert args.command == "check"
        assert args.selector == "#agree"

    def test_uncheck(self):
        parser = build_parser()
        args = parser.parse_args(["uncheck", "#newsletter"])
        assert args.command == "uncheck"
        assert args.selector == "#newsletter"


class TestWaitParser:
    """F7: wait command parser tests."""

    def test_wait_element(self):
        parser = build_parser()
        args = parser.parse_args(["wait", "element", "#loading"])
        assert args.command == "wait"
        assert args.wait_type == "element"
        assert args.target == "#loading"

    def test_wait_text(self):
        parser = build_parser()
        args = parser.parse_args(["wait", "text", "Success"])
        assert args.wait_type == "text"
        assert args.target == "Success"

    def test_wait_network_idle(self):
        parser = build_parser()
        args = parser.parse_args(["wait", "network-idle"])
        assert args.wait_type == "network-idle"

    def test_wait_ms(self):
        parser = build_parser()
        args = parser.parse_args(["wait", "5000"])
        assert args.wait_type == "5000"

    def test_wait_element_with_ref(self):
        parser = build_parser()
        args = parser.parse_args(["wait", "element", "@e0"])
        assert args.target == "@e0"


class TestDialogParser:
    """F8: dialog command parser tests."""

    def test_dialog_no_subcommand(self):
        """dialog with no subcommand should have dialog_action=None."""
        parser = build_parser()
        args = parser.parse_args(["dialog"])
        assert args.dialog_action is None

    def test_dialog_auto_dismiss(self):
        parser = build_parser()
        args = parser.parse_args(["dialog", "auto-dismiss"])
        assert args.dialog_action == "auto-dismiss"
        assert args.mode == "on"

    def test_dialog_auto_dismiss_off(self):
        parser = build_parser()
        args = parser.parse_args(["dialog", "auto-dismiss", "off"])
        assert args.mode == "off"

    def test_dialog_accept(self):
        parser = build_parser()
        args = parser.parse_args(["dialog", "accept"])
        assert args.command == "dialog"
        assert args.dialog_action == "accept"

    def test_dialog_accept_with_text(self):
        parser = build_parser()
        args = parser.parse_args(["dialog", "accept", "my input"])
        assert args.dialog_action == "accept"
        assert args.text == "my input"

    def test_dialog_dismiss(self):
        parser = build_parser()
        args = parser.parse_args(["dialog", "dismiss"])
        assert args.dialog_action == "dismiss"

    def test_dialog_info(self):
        parser = build_parser()
        args = parser.parse_args(["dialog", "info"])
        assert args.dialog_action == "info"


class TestNavigationParser:
    """F9: back, forward, reload parser tests."""

    def test_back(self):
        parser = build_parser()
        args = parser.parse_args(["back"])
        assert args.command == "back"

    def test_forward(self):
        parser = build_parser()
        args = parser.parse_args(["forward"])
        assert args.command == "forward"

    def test_reload(self):
        parser = build_parser()
        args = parser.parse_args(["reload"])
        assert args.command == "reload"


class TestTabParser:
    """F11: tab subcommand parser tests."""

    def test_tab_no_subcommand(self):
        """tab with no subcommand should have tab_action=None."""
        parser = build_parser()
        args = parser.parse_args(["tab"])
        assert args.tab_action is None

    def test_tab_list(self):
        parser = build_parser()
        args = parser.parse_args(["tab", "list"])
        assert args.command == "tab"
        assert args.tab_action == "list"

    def test_tab_create(self):
        parser = build_parser()
        args = parser.parse_args(["tab", "create"])
        assert args.tab_action == "create"

    def test_tab_create_with_url(self):
        parser = build_parser()
        args = parser.parse_args(["tab", "create", "https://example.com"])
        assert args.tab_action == "create"
        assert args.url == "https://example.com"

    def test_tab_switch(self):
        parser = build_parser()
        args = parser.parse_args(["tab", "switch", "2"])
        assert args.tab_action == "switch"
        assert args.tab_id == 2

    def test_tab_close(self):
        parser = build_parser()
        args = parser.parse_args(["tab", "close"])
        assert args.tab_action == "close"

    def test_tab_close_with_id(self):
        parser = build_parser()
        args = parser.parse_args(["tab", "close", "1"])
        assert args.tab_action == "close"
        assert args.tab_id == 1


class TestBatchParser:
    """F13: batch command parser tests."""

    def test_batch(self):
        parser = build_parser()
        args = parser.parse_args(["batch"])
        assert args.command == "batch"
        assert args.fast is False

    def test_batch_fast(self):
        parser = build_parser()
        args = parser.parse_args(["batch", "--fast"])
        assert args.fast is True
