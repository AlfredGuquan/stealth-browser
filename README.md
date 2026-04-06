# Stealth Browser

Anti-detection browser automation CLI for AI agents. Lets agents interact with websites that have bot detection (Xiaohongshu, Twitter/X) as reliably as running shell commands.

## What it does

- **Anti-detection engine** — Built on [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) (Playwright fork with 22 stealth patches). Uses your system Chrome instead of bundled Chromium for real browser fingerprints.
- **Automatic cookie management** — Extracts cookies from your real Chrome via [pycookiecheat](https://github.com/n8henrie/pycookiecheat), caches them encrypted, auto-refreshes on session expiry. No manual login needed.
- **Human behavior simulation** — Mouse movements follow Bezier curves with overshoot. Typing has variable speed and occasional typos. Scrolling has inertia. Powered by [humanization-playwright](https://pypi.org/project/humanization-playwright/).
- **Slider CAPTCHA solving** — Detects slider puzzles via OpenCV template matching, drags with human-like trajectories. Auto-retries twice before reporting failure.
- **Daemon architecture** — Browser stays alive across CLI calls via Unix socket. Sub-500ms command latency after startup.

## Requirements

- macOS
- Chrome installed (the tool uses your system Chrome, not a bundled browser)
- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## Install

```bash
git clone https://github.com/AlfredGuquan/stealth-browser.git
cd stealth-browser
uv sync
```

## Quick start

```bash
# Open a page (cookies auto-extracted from Chrome)
uv run stealth-browser --site twitter open https://x.com/home

# See interactive elements
uv run stealth-browser --site twitter snapshot -i

# Click, fill, screenshot
uv run stealth-browser --site twitter click '[data-testid="tweetButton"]'
uv run stealth-browser --site twitter fill 'input[name="text"]' "Hello world"
uv run stealth-browser --site twitter screenshot /tmp/result.png

# Close
uv run stealth-browser --site twitter close
```

## Commands

| Command | Description |
|---------|-------------|
| `open <url>` | Navigate (auto-injects cookies) |
| `snapshot [-i]` | Page snapshot (`-i` lists interactive elements) |
| `click <selector>` | Click with human-like mouse movement |
| `fill <selector> <text>` | Type with variable speed and occasional typos |
| `type <text>` | Type at current cursor position |
| `scroll <direction> [amount]` | Scroll with inertia simulation |
| `upload <selector> <file>` | File upload |
| `screenshot [path]` | Screenshot |
| `eval <js>` | Execute JavaScript |
| `get <text\|url\|title>` | Get page info |
| `close` | Close browser and daemon |
| `cookie refresh` | Force re-extract cookies from Chrome |
| `status` | Show daemon status |

Global options: `--headed` (visible browser), `--site <name>` (cookie partitioning), `--verbose`, `--timeout <ms>`.

## Design principles

1. **Results over elegance** — Whatever passes detection wins. Tech stack is a means, not an end.
2. **Zero intervention** — Cookies auto-extracted, sessions auto-maintained. Human needed only when login truly expires.
3. **One tool, full pipeline** — Cookie reuse + anti-detection + behavior simulation in a single CLI.
4. **Reliable over universal** — Verified against specific sites (XHS, Twitter). Not a generic "anti-detection framework."
5. **Observable** — Clear diagnostics on failure. Zero noise on success.

## Tested on

- Twitter/X — posting, reading feed
- Xiaohongshu (小红书) — posting with images, reading

## License

MIT
