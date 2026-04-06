"""Slider CAPTCHA detection and solving.

Strategy:
1. detect() -- look for common slider CAPTCHA elements on the page
2. solve() -- screenshot -> OpenCV template matching to find gap -> human-like drag

Supports:
- Puzzle slider (e.g., Xiaohongshu's slide-to-fit-piece)
- NOT reCAPTCHA, Turnstile, image selection -- those return unsupported error

Max retries: 2. On failure, saves screenshot to /tmp/ for diagnosis.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass

import cv2
import numpy as np
from patchright.async_api import Page

from .behavior import HumanBehavior

logger = logging.getLogger("stealth_browser.captcha")

# Common selectors for slider CAPTCHA elements across sites
SLIDER_SELECTORS = [
    # Xiaohongshu / generic Chinese sites
    ".captcha-slider",
    ".slide-verify",
    ".slider-btn",
    '[class*="captcha"][class*="slider"]',
    '[class*="slide"][class*="verify"]',
    '[class*="drag"][class*="verify"]',
    # GEETEST
    ".geetest_slider_button",
    ".geetest_slider",
    # TencentCaptcha
    "#tcaptcha_drag_thumb",
    # Generic
    '[data-type="slider"]',
    '[class*="slider-captcha"]',
]

CAPTCHA_BG_SELECTORS = [
    ".captcha-bg",
    ".slide-verify-image",
    '[class*="captcha"][class*="bg"]',
    '[class*="captcha"] img',
    ".geetest_canvas_bg",
    ".geetest_canvas_fullbg",
    '[class*="captcha-image"]',
]

# Unsupported CAPTCHA types -- detect and bail out
UNSUPPORTED_SELECTORS = [
    # reCAPTCHA
    ".g-recaptcha",
    'iframe[src*="recaptcha"]',
    # Cloudflare Turnstile
    'iframe[src*="turnstile"]',
    ".cf-turnstile",
    # hCaptcha
    ".h-captcha",
    'iframe[src*="hcaptcha"]',
]


@dataclass
class CaptchaResult:
    solved: bool
    message: str
    screenshot_path: str | None = None


class CaptchaSolver:
    """Slider CAPTCHA detector and solver."""

    def __init__(self, page: Page, behavior: HumanBehavior):
        self.page = page
        self.behavior = behavior

    async def detect(self) -> str | None:
        """Detect if the page has a CAPTCHA.

        Returns:
            "slider" if a slider CAPTCHA is found
            "unsupported" if a non-slider CAPTCHA is found
            None if no CAPTCHA detected
        """
        # Check unsupported types first
        for sel in UNSUPPORTED_SELECTORS:
            try:
                count = await self.page.locator(sel).count()
                if count > 0:
                    return "unsupported"
            except Exception:
                continue

        # Check slider types
        for sel in SLIDER_SELECTORS:
            try:
                count = await self.page.locator(sel).count()
                if count > 0:
                    return "slider"
            except Exception:
                continue

        return None

    async def solve(self, max_retries: int = 2) -> CaptchaResult:
        """Attempt to solve a slider CAPTCHA.

        Steps:
        1. Find the slider thumb and background image elements
        2. Screenshot the CAPTCHA area
        3. Use OpenCV template matching to find the gap position
        4. Calculate the drag distance
        5. Use human-like drag to move the slider
        """
        captcha_type = await self.detect()

        if captcha_type is None:
            return CaptchaResult(solved=True, message="no CAPTCHA detected")

        if captcha_type == "unsupported":
            screenshot_path = await self._save_failure_screenshot()
            return CaptchaResult(
                solved=False,
                message="unsupported CAPTCHA type (reCAPTCHA/Turnstile/hCaptcha)",
                screenshot_path=screenshot_path,
            )

        # Attempt to solve slider CAPTCHA
        for attempt in range(1, max_retries + 1):
            logger.info(f"CAPTCHA solve attempt {attempt}/{max_retries}")
            try:
                result = await self._solve_slider(attempt)
                if result.solved:
                    return result
            except Exception as e:
                logger.warning(f"CAPTCHA attempt {attempt} failed: {e}")

            # Wait before retry
            if attempt < max_retries:
                await asyncio.sleep(1.5)

        # All retries failed
        screenshot_path = await self._save_failure_screenshot()
        return CaptchaResult(
            solved=False,
            message=f"slider CAPTCHA solve failed after {max_retries} attempts",
            screenshot_path=screenshot_path,
        )

    async def _solve_slider(self, attempt: int) -> CaptchaResult:
        """Single attempt at solving a slider CAPTCHA."""
        # Find the slider thumb
        thumb = None
        for sel in SLIDER_SELECTORS:
            loc = self.page.locator(sel)
            if await loc.count() > 0:
                thumb = loc.first
                break

        if thumb is None:
            return CaptchaResult(solved=False, message="slider thumb not found")

        # Find the background image
        bg_element = None
        for sel in CAPTCHA_BG_SELECTORS:
            loc = self.page.locator(sel)
            if await loc.count() > 0:
                bg_element = loc.first
                break

        if bg_element is None:
            # Fallback: screenshot the full page area around the CAPTCHA
            bg_element = thumb

        # Screenshot the CAPTCHA background for OpenCV analysis
        bg_bytes = await bg_element.screenshot()
        bg_array = np.frombuffer(bg_bytes, dtype=np.uint8)
        bg_image = cv2.imdecode(bg_array, cv2.IMREAD_COLOR)

        if bg_image is None:
            return CaptchaResult(solved=False, message="failed to capture CAPTCHA image")

        # Try to get the puzzle piece image (if separate element exists)
        piece_image = await self._get_puzzle_piece(bg_image)

        # Detect gap position
        if piece_image is not None:
            gap_x = self._detect_gap_template(bg_image, piece_image)
        else:
            gap_x = self._detect_gap_edge(bg_image)

        if gap_x is None:
            return CaptchaResult(
                solved=False, message="could not detect gap position"
            )

        # Get thumb position and calculate drag distance
        thumb_box = await thumb.bounding_box()
        if thumb_box is None:
            return CaptchaResult(solved=False, message="cannot get slider position")

        # The drag distance is from the thumb center to the gap x position,
        # scaled to the actual page coordinates
        bg_box = await bg_element.bounding_box()
        if bg_box is None:
            bg_box = thumb_box

        # Scale gap_x from image coordinates to page coordinates
        scale = bg_box["width"] / bg_image.shape[1] if bg_image.shape[1] > 0 else 1
        drag_distance = gap_x * scale

        # Calculate absolute coordinates
        from_x = thumb_box["x"] + thumb_box["width"] / 2
        from_y = thumb_box["y"] + thumb_box["height"] / 2
        to_x = from_x + drag_distance
        to_y = from_y

        logger.info(
            f"gap_x={gap_x}, scale={scale:.2f}, drag={drag_distance:.0f}px, "
            f"from=({from_x:.0f},{from_y:.0f}) to=({to_x:.0f},{to_y:.0f})"
        )

        # Execute human-like drag
        await self.behavior.drag(from_x, from_y, to_x, to_y)

        # Wait for verification result
        await asyncio.sleep(1.5)

        # Check if CAPTCHA is still present (solved = disappeared)
        still_present = await self.detect()
        if still_present == "slider":
            return CaptchaResult(
                solved=False,
                message=f"slider still present after drag (attempt {attempt})",
            )

        return CaptchaResult(solved=True, message="slider CAPTCHA solved")

    async def _get_puzzle_piece(
        self, bg_image: np.ndarray
    ) -> np.ndarray | None:
        """Try to extract the puzzle piece image from the page."""
        piece_selectors = [
            ".captcha-piece",
            ".slide-verify-block",
            '[class*="captcha"][class*="piece"]',
            '[class*="captcha"][class*="block"]',
            ".geetest_canvas_slice",
        ]

        for sel in piece_selectors:
            try:
                loc = self.page.locator(sel)
                if await loc.count() > 0:
                    piece_bytes = await loc.first.screenshot()
                    arr = np.frombuffer(piece_bytes, dtype=np.uint8)
                    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if img is not None:
                        return img
            except Exception:
                continue

        return None

    def _detect_gap_template(
        self, background: np.ndarray, piece: np.ndarray
    ) -> int | None:
        """Template matching: find where the puzzle piece fits in the background."""
        bg_gray = cv2.cvtColor(background, cv2.COLOR_BGR2GRAY)
        piece_gray = cv2.cvtColor(piece, cv2.COLOR_BGR2GRAY)

        result = cv2.matchTemplate(bg_gray, piece_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val < 0.5:
            logger.warning(f"template match confidence too low: {max_val:.3f}")
            return None

        return max_loc[0]

    def _detect_gap_edge(self, background: np.ndarray) -> int | None:
        """Edge detection fallback: find the dark rectangular gap."""
        gray = cv2.cvtColor(background, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)

        kernel = np.ones((3, 3), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)

        contours, _ = cv2.findContours(
            edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        h, w = background.shape[:2]
        # Expect gap to be roughly 40-80px square, in the right 60% of image
        min_size = min(h, w) * 0.15
        max_size = min(h, w) * 0.6

        candidates = []
        for contour in contours:
            x, y, cw, ch = cv2.boundingRect(contour)
            aspect = cw / ch if ch > 0 else 0
            if (
                0.7 < aspect < 1.4
                and min_size < cw < max_size
                and x > w * 0.3  # Gap is usually not at the left edge
            ):
                area_score = abs(cw * ch - (min_size * 2) ** 2)
                candidates.append((x, area_score))

        if not candidates:
            return None

        # Return the x position of the best candidate
        candidates.sort(key=lambda c: c[1])
        return candidates[0][0]

    async def _save_failure_screenshot(self) -> str:
        """Save a full-page screenshot for failed CAPTCHA diagnosis."""
        path = tempfile.mktemp(prefix="captcha-fail-", suffix=".png", dir="/tmp")
        await self.page.screenshot(path=path, full_page=True)
        return path
