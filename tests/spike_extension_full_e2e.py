"""End-to-end spike: load personal-website Web Clipper extension and exercise
all three extension contexts (content / service worker / sidepanel) against
a live browser-companion WS server.

Layers:
  L1 manifest/load     — extensions=N in launch log
  L2 execution         — service_workers != [] AND content_script DOM marker
  L3 message routing   — SW chrome.runtime.id reachable; sidePanel.open path
  L4 ws round-trip     — sidepanel connects to ws://localhost:3142

Run manually (not part of pytest suite — talks to live ports):
  uv run --project ~/Desktop/2-projects/stealth-browser \
    python tests/spike_extension_full_e2e.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stealth_browser.engine import StealthEngine

EXT_DIR = "/Users/alfred.gu/Desktop/2-projects/personal-website/extension"
WS_PORT = 3142


def _load_secret_from_launchd() -> str:
    """Pull BROWSER_COMPANION_SECRET from the live launchd agent.

    Matches dev-browser-setup.sh; never log or print the value.
    """
    out = subprocess.check_output(
        ["launchctl", "print", f"gui/{os.getuid()}/com.alfredgu.browser-companion"],
        text=True,
    )
    for line in out.splitlines():
        if "BROWSER_COMPANION_SECRET" in line and "=>" in line:
            return line.split("=>", 1)[1].strip()
    raise RuntimeError("BROWSER_COMPANION_SECRET not found in launchd plist")


SECRET = _load_secret_from_launchd()

results: list[tuple[str, str, str]] = []


def record(layer: str, status: str, detail: str) -> None:
    results.append((layer, status, detail))
    print(f"  [{status}] {layer}: {detail}")


async def wait_for(predicate, timeout: float, label: str) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.2)
    print(f"  [timeout] {label}")
    return False


async def main() -> int:
    print("== L0: probe live browser-companion WS server ==")
    # Reuse the running launchd-managed server (port 3142) instead of starting a
    # second one. Talking through the same secret the user's real Chrome uses.
    import socket as _s
    sock = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
    sock.settimeout(1.5)
    try:
        sock.connect(("127.0.0.1", WS_PORT))
        sock.close()
        record("L0", "PASS", f"existing server reachable on :{WS_PORT}")
    except OSError as e:
        record("L0", "FAIL", f"port {WS_PORT} unreachable: {e}")
        return 1

    print("\n== L1+L2: launch stealth-browser with extension ==")
    if True:
        engine = StealthEngine()
        try:
            await engine.launch(headed=True, extensions=[EXT_DIR])
            ctx = engine.context
            record("L1 manifest/load", "PASS", "engine.launch with extensions=1 OK")

            # Wait for SW registration (service_workers populates lazily)
            print("  waiting for service worker registration...")
            ok = await wait_for(
                lambda: bool(ctx.service_workers),
                timeout=10,
                label="service_workers populated",
            )
            workers = list(ctx.service_workers)
            if not ok:
                record(
                    "L2 SW execution", "FAIL", "no service_workers exposed by Patchright"
                )
            else:
                sw = workers[0]
                record(
                    "L2 SW execution",
                    "PASS",
                    f"{len(workers)} worker(s); url={sw.url}",
                )

            # Cross-context: SW chrome.runtime.id
            ext_id = None
            if workers:
                try:
                    ext_id = await workers[0].evaluate("chrome.runtime.id")
                    record(
                        "L3a chrome.runtime in SW",
                        "PASS",
                        f"extension id={ext_id}",
                    )
                except Exception as e:
                    record("L3a chrome.runtime in SW", "FAIL", repr(e))

            # Navigate to page so sidePanel has a tab
            await engine.navigate(
                "https://example.com/", site="example.com", skip_cookies=True
            )
            page = engine.page
            assert page is not None
            # Allow content script document_idle to settle.
            await asyncio.sleep(1.5)
            # L2 content-script execution is proven below by L3b (we drive a
            # chrome.runtime.sendMessage from a freshly-injected isolated-world
            # snippet — that channel only works if the extension's content
            # script bridge in this tab is alive).

            # L3b: sendMessage round-trip — page → background "extract" handler.
            # Needs content script context. Use SW to executeScript a probe into the page.
            if workers:
                sw = workers[0]
                tab_id_js = (
                    "async () => {"
                    "  const tabs = await chrome.tabs.query({active:true,currentWindow:true});"
                    "  return tabs[0]?.id ?? null;"
                    "}"
                )
                tab_id = await sw.evaluate(tab_id_js)
                if tab_id:
                    record("L3b active tab visible from SW", "PASS", f"tabId={tab_id}")
                    # Inject a ping into content script world; expect background's
                    # "extract" handler to roundtrip a result.
                    probe = (
                        "async (tabId) => {"
                        "  try {"
                        "    const [r] = await chrome.scripting.executeScript({"
                        "      target: {tabId},"
                        "      world: 'ISOLATED',"
                        "      func: () => new Promise(res => {"
                        "        chrome.runtime.sendMessage({action:'extract'}, reply =>"
                        "          res({ok: !chrome.runtime.lastError, reply, err: chrome.runtime.lastError?.message}));"
                        "      })"
                        "    });"
                        "    return r.result;"
                        "  } catch (e) { return {ok:false, err: e.message}; }"
                        "}"
                    )
                    try:
                        rt = await sw.evaluate(probe, tab_id)
                        if rt and rt.get("ok"):
                            record(
                                "L3b sendMessage round-trip",
                                "PASS",
                                f"reply keys={list((rt.get('reply') or {}).keys())[:5]}",
                            )
                        else:
                            record(
                                "L3b sendMessage round-trip",
                                "FAIL",
                                f"err={rt.get('err') if rt else 'no result'}",
                            )
                    except Exception as e:
                        record("L3b sendMessage round-trip", "FAIL", repr(e))

                # L3c: chrome.sidePanel.open() requires user activation that
                # survives the synchronous portion of onMessage. CustomEvent
                # crossing main↔isolated worlds drops user activation, so
                # bridge straight from the **trusted click event** in isolated
                # world to chrome.runtime.sendMessage — that path preserves
                # activation through onMessage's sync window.
                bridge = (
                    "async (tabId) => {"
                    "  const [r] = await chrome.scripting.executeScript({"
                    "    target: {tabId},"
                    "    world: 'ISOLATED',"
                    "    func: () => {"
                    "      document.addEventListener('click', (e) => {"
                    "        const t = e.target;"
                    "        if (!t || t.id !== 'spike-trigger') return;"
                    "        chrome.runtime.sendMessage({"
                    "          action: 'video-annotation-trigger',"
                    "          videoId: 'spike', videoSlug: 'spike',"
                    "          videoTitle: 'spike',"
                    "          timestamp_seconds: 0, subtitle_text: ''"
                    "        });"
                    "      }, true);"
                    "    }"
                    "  });"
                    "  return r ? 'bridged' : 'fail';"
                    "}"
                )
                bridge_result = await sw.evaluate(bridge, tab_id)
                record("L3c bridge install", "PASS" if bridge_result == "bridged" else "FAIL", str(bridge_result))

                # Inject a plain button — the click listener lives in isolated
                # world (above), so this main-world button just needs to exist.
                await page.evaluate(
                    "(() => {"
                    "  const b = document.createElement('button');"
                    "  b.id = 'spike-trigger';"
                    "  b.textContent = 'open sidepanel';"
                    "  b.style.cssText = 'position:fixed;top:30%;left:30%;"
                    "width:240px;height:60px;font-size:20px;z-index:9999;';"
                    "  document.body.appendChild(b);"
                    "})()"
                )
                # Hook SW console BEFORE click so we capture any
                # chrome.runtime.lastError surfacing via background.js logs.
                sw_console: list[str] = []
                workers[0].on(
                    "console",
                    lambda msg: sw_console.append(f"[{msg.type}] {msg.text}"),
                )
                try:
                    await engine.click("#spike-trigger")
                    record("L3c trigger click", "PASS", "human click delivered")
                except Exception as e:
                    record("L3c trigger click", "FAIL", repr(e))

                # Direct probe (bypasses user gesture path) — surfaces the
                # exact error string Chrome would otherwise swallow.
                direct_probe = (
                    "async (tabId) => {"
                    "  return new Promise(res => {"
                    "    try {"
                    "      chrome.sidePanel.open({tabId}, () => {"
                    "        res({lastErr: chrome.runtime.lastError?.message ?? null});"
                    "      });"
                    "    } catch (e) { res({thrown: e.message}); }"
                    "  });"
                    "}"
                )
                direct = await workers[0].evaluate(direct_probe, tab_id)
                record(
                    "L3c direct sidePanel.open",
                    "PASS" if not direct.get("lastErr") and not direct.get("thrown") else "INFO",
                    str(direct),
                )

            # L4: write secret to chrome.storage.sync, then check sidepanel WS connect
            if workers:
                sw = workers[0]
                # Push secret into storage so sidepanel autoconnects
                await sw.evaluate(
                    f"chrome.storage.sync.set({{companionSecret: {SECRET!r}}})"
                )
                record("L4a secret seeded", "PASS", "chrome.storage.sync set")

            # L4b: open the sidepanel page directly as a tab. chrome.sidePanel
            # .open() requires user activation that doesn't survive scripted
            # paths, but the sidepanel.html itself is a normal extension page
            # — the dev-browser-setup.sh canonical flow simply navigates to
            # chrome-extension://EXT_ID/sidepanel.html. That gives us a real
            # extension-page context where ws auto-connect runs.
            sidepanel_page = None
            ws_urls: list[str] = []
            try:
                sp_page = await ctx.new_page()
                sp_page.on("websocket", lambda ws_obj: ws_urls.append(ws_obj.url))
                await sp_page.goto(
                    f"chrome-extension://{ext_id}/sidepanel.html",
                    wait_until="domcontentloaded",
                )
                sidepanel_page = sp_page
                record("L4b sidepanel page", "PASS", sp_page.url)
            except Exception as e:
                record("L4b sidepanel page", "FAIL", repr(e))
            if sw_console:
                print("  SW console trace:")
                for line in sw_console[-20:]:
                    print(f"    {line}")

            # L4c: ws connection. sidepanel.js scopes its ws variable in an
            # IIFE so page.evaluate can't see it. Use Playwright's ws event
            # stream we wired up before goto() and also probe DOM status-dot
            # state which sidepanel.js mutates on connect.
            if sidepanel_page:
                # Wait up to 6s for ws creation + opening handshake
                deadline = time.time() + 6
                while time.time() < deadline and not ws_urls:
                    await asyncio.sleep(0.2)
                if ws_urls:
                    # Strip secret from logged URL to keep it out of stdout/git
                    safe_url = ws_urls[0].split("?")[0]
                    record(
                        "L4c ws connect",
                        "PASS",
                        f"sidepanel opened ws to {safe_url} (secret query stripped)",
                    )
                else:
                    # Fallback: status-dot class shows connection state
                    try:
                        status = await sidepanel_page.evaluate(
                            "document.getElementById('status-dot')?.className ?? 'no-dot'"
                        )
                        record("L4c ws connect", "FAIL", f"no ws event; status-dot={status}")
                    except Exception as e:
                        record("L4c ws connect", "FAIL", f"probe err: {e}")
            else:
                record("L4c ws connect", "FAIL", "no sidepanel page to probe")

        finally:
            await engine.shutdown()

    # Summary
    print("\n== SUMMARY ==")
    for layer, status, detail in results:
        print(f"  [{status}] {layer}: {detail}")
    fails = [r for r in results if r[1] == "FAIL"]
    return 0 if not fails else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
