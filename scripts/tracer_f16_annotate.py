"""F16 tracer: validate bounding_box <-> screenshot coordinate space + Pillow overlay.

Tests:
A) Default viewport (1280x720, scale=1): screenshot PNG dimensions vs bounding_box
B) deviceScaleFactor=2 (retina): same checks
C) After scrolling: confirm bounding_box returns viewport-relative coords
D) Pillow draw template: overlay numbered yellow labels on the screenshot
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from patchright.async_api import async_playwright


HTML = """
<!doctype html>
<meta charset="utf-8">
<title>F16 fixture</title>
<style>
  body { margin: 0; font-family: sans-serif; }
  .target { display: block; margin: 40px; padding: 20px 30px; }
  .a { background: #fcd; }
  .b { background: #cfd; }
  .c { background: #ccf; }
  .spacer { height: 1500px; }
</style>
<button class="target a">A</button>
<button class="target b">B</button>
<button class="target c">C</button>
<div class="spacer"></div>
<button class="target a" id="far">FAR</button>
"""


def draw_overlay(png_bytes: bytes, boxes: list[dict], scale: float, out: Path) -> None:
    """Pillow template: overlay [N] yellow label on each element bounding box.

    `boxes` is a list of {ref, bbox} where bbox is in CSS pixels.
    `scale` is devicePixelRatio of the screenshot (1.0 or 2.0).
    """
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf", int(18 * scale)
        )
    except Exception:
        font = ImageFont.load_default()

    for i, b in enumerate(boxes, start=1):
        bb = b["bbox"]
        x = bb["x"] * scale
        y = bb["y"] * scale
        w = bb["width"] * scale
        h = bb["height"] * scale
        # Outline the element
        draw.rectangle([x, y, x + w, y + h], outline=(255, 200, 0, 255), width=max(2, int(2 * scale)))
        # Label background top-left
        label = f"[{i}]"
        # textbbox is preferred over textsize in modern Pillow
        try:
            l, t, r, btm = draw.textbbox((0, 0), label, font=font)
            tw, th = r - l, btm - t
        except Exception:
            tw, th = 22 * int(scale), 22 * int(scale)
        pad = int(4 * scale)
        lx, ly = x, y
        draw.rectangle([lx, ly, lx + tw + 2 * pad, ly + th + 2 * pad], fill=(255, 230, 0, 230))
        draw.text((lx + pad, ly + pad - 2), label, fill=(0, 0, 0, 255), font=font)

    Image.alpha_composite(img, overlay).save(out, "PNG")


async def measure(page, label: str) -> tuple[bytes, list[dict], int, int]:
    """Take screenshot, collect bounding_box for each .target, return everything."""
    png = await page.screenshot()
    img = Image.open(io.BytesIO(png))
    print(f"  [{label}] PNG size = {img.size}")

    locs = page.locator(".target")
    n = await locs.count()
    boxes = []
    for i in range(n):
        bb = await locs.nth(i).bounding_box()
        text = (await locs.nth(i).inner_text()).strip()
        print(f"    el#{i} text={text!r:>6} bbox={bb}")
        if bb:
            boxes.append({"ref": f"@e{i+1}", "bbox": bb, "text": text})
    return png, boxes, img.size[0], img.size[1]


async def main() -> None:
    out_dir = Path("scripts/_tracer_f16_out")
    out_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")

        # ---- A: default viewport, scale=1 ----
        ctx_a = await browser.new_context(viewport={"width": 1280, "height": 720})
        page_a = await ctx_a.new_page()
        await page_a.set_content(HTML)
        print("== A: viewport 1280x720, deviceScaleFactor default ==")
        png, boxes, pw, ph = await measure(page_a, "A")
        print(f"    viewport vs PNG: viewport=(1280,720) png=({pw},{ph})  -> scale = {pw / 1280}")
        draw_overlay(png, boxes[:3], scale=pw / 1280, out=out_dir / "A_default.png")

        # ---- B: retina, scale=2 ----
        ctx_b = await browser.new_context(
            viewport={"width": 1280, "height": 720}, device_scale_factor=2
        )
        page_b = await ctx_b.new_page()
        await page_b.set_content(HTML)
        print("\n== B: viewport 1280x720, deviceScaleFactor=2 ==")
        png, boxes, pw, ph = await measure(page_b, "B")
        print(f"    viewport vs PNG: viewport=(1280,720) png=({pw},{ph})  -> scale = {pw / 1280}")
        draw_overlay(png, boxes[:3], scale=pw / 1280, out=out_dir / "B_retina.png")

        # ---- C: after scrolling ----
        ctx_c = await browser.new_context(viewport={"width": 1280, "height": 720})
        page_c = await ctx_c.new_page()
        await page_c.set_content(HTML)
        await page_c.evaluate("window.scrollTo(0, 1200)")
        print("\n== C: viewport 1280x720 + scrolled to y=1200 ==")
        scroll_y = await page_c.evaluate("window.scrollY")
        print(f"    window.scrollY = {scroll_y}")
        png, boxes, pw, ph = await measure(page_c, "C")
        far = page_c.locator("#far")
        far_bb = await far.bounding_box()
        print(f"    #far bbox = {far_bb}")
        # Compose visible-only boxes (those with bb.y in viewport)
        visible = [b for b in boxes if 0 <= b["bbox"]["y"] <= 720]
        print(f"    visible-after-scroll boxes: {[b['text'] for b in visible]}")
        draw_overlay(png, visible if visible else boxes[:3], scale=pw / 1280, out=out_dir / "C_scrolled.png")

        await browser.close()
        print(f"\nSaved overlays to {out_dir}/")


if __name__ == "__main__":
    asyncio.run(main())
