"""Pillow overlay for annotated screenshots (F16).

Draws yellow bounding boxes and numeric labels on top of a PNG screenshot.
The DOM is never touched -- annotation happens entirely on the pixel level
so the page state stays clean.

DPR (device pixel ratio) is computed at runtime from the PNG width and the
CSS viewport width -- retina displays produce a 2x PNG and boxes must be
scaled accordingly. Hardcoding DPR is wrong; the tracer verified that.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

_FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def overlay_labels(
    png_bytes: bytes,
    boxes: list[dict],
    *,
    viewport_css_width: int,
) -> bytes:
    """Draw yellow boxes + numeric labels on a PNG screenshot.

    Args:
        png_bytes: the raw PNG bytes from page.screenshot(full_page=True)
        boxes: list of {bbox: {x,y,width,height}, ref, tag, text}. Coords are
            in CSS pixels (Playwright bounding_box() result). The first box
            becomes label [1], the second becomes [2], etc.
        viewport_css_width: page viewport width in CSS pixels, used to derive
            DPR from PNG width / viewport width.

    Returns: PNG bytes with the overlay composited in.

    Caller is responsible for scrolling to (0,0) before capturing png_bytes
    so that ``bbox.y`` is aligned with the top of the full_page screenshot.
    """
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    dpr = img.size[0] / viewport_css_width  # robust DPR detection
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    try:
        font = ImageFont.truetype(_FONT_PATH, int(18 * dpr))
    except Exception:
        font = ImageFont.load_default()

    for i, b in enumerate(boxes, start=1):
        bb = b["bbox"]
        x = bb["x"] * dpr
        y = bb["y"] * dpr
        w = bb["width"] * dpr
        h = bb["height"] * dpr
        draw.rectangle(
            [x, y, x + w, y + h],
            outline=(255, 200, 0, 255),
            width=max(2, int(2 * dpr)),
        )
        label = f"[{i}]"
        l, t, r, btm = draw.textbbox((0, 0), label, font=font)
        tw, th = r - l, btm - t
        pad = int(4 * dpr)
        # Place label just above the element when there's room; otherwise
        # tuck it inside at the top-left so it's always visible.
        ly = y - th - 2 * pad if y > th + 2 * pad else y
        draw.rectangle(
            [x, ly, x + tw + 2 * pad, ly + th + 2 * pad],
            fill=(255, 230, 0, 230),
        )
        draw.text(
            (x + pad, ly + pad - 2),
            label,
            fill=(0, 0, 0, 255),
            font=font,
        )

    out = io.BytesIO()
    Image.alpha_composite(img, overlay).save(out, "PNG")
    return out.getvalue()
