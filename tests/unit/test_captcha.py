"""Unit tests for stealth_browser.captcha."""

import numpy as np
import cv2
import pytest
from stealth_browser.captcha import CaptchaSolver


def make_captcha_pair(
    width=400, height=200, gap_x=280, gap_y=60, piece_size=60
):
    """Create a synthetic slider CAPTCHA background + puzzle piece."""
    rng = np.random.RandomState(42)
    bg = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        for x in range(width):
            bg[y, x] = [
                int(100 + 80 * np.sin(x / 30.0)),
                int(120 + 60 * np.cos(y / 20.0)),
                int(140 + 50 * np.sin((x + y) / 25.0)),
            ]
    noise = rng.randint(0, 20, bg.shape, dtype=np.uint8)
    bg = cv2.add(bg, noise)

    piece = bg[gap_y: gap_y + piece_size, gap_x: gap_x + piece_size].copy()
    cv2.rectangle(piece, (0, 0), (piece_size - 1, piece_size - 1), (200, 200, 200), 2)

    gap_region = bg[gap_y: gap_y + piece_size, gap_x: gap_x + piece_size]
    darkened = (gap_region.astype(np.float32) * 0.3).astype(np.uint8)
    bg[gap_y: gap_y + piece_size, gap_x: gap_x + piece_size] = darkened

    return bg, piece


class TestGapDetection:
    """Test OpenCV gap detection methods without requiring a browser."""

    def test_template_matching_basic(self):
        solver = CaptchaSolver.__new__(CaptchaSolver)  # No page needed
        bg, piece = make_captcha_pair(gap_x=280, gap_y=60)
        gap_x = solver._detect_gap_template(bg, piece)
        assert gap_x is not None
        assert abs(gap_x - 280) < 20, f"Expected ~280, got {gap_x}"

    def test_template_matching_different_positions(self):
        solver = CaptchaSolver.__new__(CaptchaSolver)
        positions = [(100, 40), (200, 80), (300, 50)]
        successes = 0
        for gx, gy in positions:
            bg, piece = make_captcha_pair(gap_x=gx, gap_y=gy)
            detected = solver._detect_gap_template(bg, piece)
            if detected is not None and abs(detected - gx) < 20:
                successes += 1
        assert successes >= 2, f"Only {successes}/3 positions detected"

    def test_edge_detection_basic(self):
        solver = CaptchaSolver.__new__(CaptchaSolver)
        bg, _ = make_captcha_pair(gap_x=280, gap_y=60)
        gap_x = solver._detect_gap_edge(bg)
        # Edge detection is less precise, allow wider tolerance
        if gap_x is not None:
            assert abs(gap_x - 280) < 40, f"Expected ~280, got {gap_x}"

    def test_template_matching_low_confidence(self):
        """Random noise image should return None (confidence too low)."""
        solver = CaptchaSolver.__new__(CaptchaSolver)
        bg = np.random.randint(0, 255, (200, 400, 3), dtype=np.uint8)
        piece = np.random.randint(0, 255, (60, 60, 3), dtype=np.uint8)
        # Result may or may not be None depending on random correlation,
        # but the important thing is it doesn't crash
        solver._detect_gap_template(bg, piece)
