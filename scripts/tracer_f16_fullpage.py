"""F16 supplemental: full_page=True screenshot vs bounding_box.

The current stealth-browser engine uses full_page=True for screenshots.
This needs verification: bbox is viewport-relative, but full_page PNG
spans the whole document — so the mapping must add scrollY.
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
<style>
  body { margin: 0; font-family: sans-serif; }
  .target { display: block; margin: 40px; padding: 20px 30px; background: #fcd; }
  .spacer { height: 1500px; }
</style>
<button class="target" id="top">TOP</button>
<div class="spacer"></div>
<button class="target" id="far">FAR</button>
"""


async def main() -> None:
    out_dir = Path("scripts/_tracer_f16_out")
    out_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        ctx = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await ctx.new_page()
        await page.set_content(HTML)

        # Take full-page screenshot
        png = await page.screenshot(full_page=True)
        img = Image.open(io.BytesIO(png))
        print(f"== full_page screenshot ==")
        print(f"  PNG size = {img.size}  (viewport=1280x720)")
        scroll_y = await page.evaluate("window.scrollY")
        print(f"  scrollY at screenshot = {scroll_y}")

        for sel in ["#top", "#far"]:
            bb = await page.locator(sel).bounding_box()
            print(f"  {sel} bbox={bb}")

        # Now scroll, then full_page screenshot
        await page.evaluate("window.scrollTo(0, 800)")
        png2 = await page.screenshot(full_page=True)
        img2 = Image.open(io.BytesIO(png2))
        print(f"\n== full_page screenshot AFTER scrollTo(0, 800) ==")
        print(f"  PNG size = {img2.size}")
        scroll_y = await page.evaluate("window.scrollY")
        print(f"  scrollY now = {scroll_y}")
        for sel in ["#top", "#far"]:
            bb = await page.locator(sel).bounding_box()
            print(f"  {sel} bbox={bb}")
        # Note: full_page screenshot resets scroll internally — playwright restores after.

        # Build overlay using formula: pixel_y = (bbox.y + savedScrollY) * dpr
        # for default DPR=1, savedScrollY=0 the formula collapses to bbox coords directly.

        # Confirm: take a fresh full_page from scroll=0 and overlay
        await page.evaluate("window.scrollTo(0, 0)")
        png3 = await page.screenshot(full_page=True)
        img3 = Image.open(io.BytesIO(png3)).convert("RGBA")
        overlay = Image.new("RGBA", img3.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        try:
            font = ImageFont.truetype(
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf", 22
            )
        except Exception:
            font = ImageFont.load_default()

        for i, sel in enumerate(["#top", "#far"], start=1):
            bb = await page.locator(sel).bounding_box()
            assert bb is not None
            x, y, w, h = bb["x"], bb["y"], bb["width"], bb["height"]
            draw.rectangle([x, y, x + w, y + h], outline=(255, 200, 0, 255), width=3)
            label = f"[{i}]"
            l, t, r, btm = draw.textbbox((0, 0), label, font=font)
            tw, th = r - l, btm - t
            draw.rectangle([x, y, x + tw + 10, y + th + 10], fill=(255, 230, 0, 230))
            draw.text((x + 5, y + 3), label, fill=(0, 0, 0, 255), font=font)

        out = out_dir / "fullpage_overlay.png"
        Image.alpha_composite(img3, overlay).save(out, "PNG")
        print(f"\n  saved: {out}")
        print(f"  -> visually verify [1] is on TOP near top, [2] is on FAR near bottom")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
