"""Human behavior simulation facade.

Wraps humanization-playwright to provide the interface needed by the CLI:
  - click(selector): hover -> Bezier move -> click
  - fill(selector, text): click input -> variable-speed typing with typos + backspace
  - scroll(direction, amount): inertial scroll with random pauses
  - drag(from_x, from_y, to_x, to_y): Bezier curve drag for CAPTCHA sliders

Key constraints (from tracer findings):
  - Do NOT use undetected_launch() -- it forces headed mode
  - Construct Humanization(page, config) directly with our own Patchright page
  - drag_to() only accepts two Locators -- use manual mouse ops for pixel-offset drags
  - type_at() doesn't do typos -- we implement typo+backspace ourselves
  - humanization-playwright creates humanization.log on import -- redirect loguru
"""

from __future__ import annotations

import asyncio
import logging
import random
import string

from patchright.async_api import Page

# Redirect humanization-playwright's loguru handler before first use.
# The library adds a file handler in __init__.py; we remove it.
try:
    from loguru import logger as _loguru_logger

    _loguru_logger.remove()  # Remove all handlers (including the file one)
except ImportError:
    pass

from humanization import Humanization, HumanizationConfig

logger = logging.getLogger("stealth_browser.behavior")


class HumanBehavior:
    """Facade for human-like browser interactions.

    Usage:
        hb = HumanBehavior(page)
        await hb.click(page.locator("#btn"))
        await hb.fill(page.locator("#input"), "hello world")
        await hb.scroll("down", 3)
    """

    def __init__(self, page: Page, *, fast: bool = False):
        self.page = page
        config = HumanizationConfig(
            fast=fast,
            humanize=True,
            characters_per_minute=350,
            stealth_mode=False,
        )
        self._h = Humanization(page, config)

    async def click(self, selector: str) -> None:
        """Click an element with human-like hover + Bezier move + click."""
        locator = self.page.locator(selector)
        # Hover first (50-300ms dwell)
        await self._h.move_to(locator)
        await asyncio.sleep(random.uniform(0.05, 0.3))
        await self._h.click_at(locator)

    async def fill(self, selector: str, text: str) -> None:
        """Click an input, then type with variable speed and occasional typos.

        Typo rate: 3-8% of characters get a random wrong char + backspace.
        """
        locator = self.page.locator(selector)
        # Click to focus
        await self._h.click_at(locator)
        await asyncio.sleep(random.uniform(0.1, 0.3))

        # Type character by character with variable delays and typos
        typo_rate = random.uniform(0.03, 0.08)

        for i, char in enumerate(text):
            # Decide if this character gets a typo
            if random.random() < typo_rate and char not in ("\n", "\t"):
                # Type a wrong character first
                wrong = random.choice(
                    string.ascii_lowercase.replace(char.lower(), "")
                )
                await self.page.keyboard.press(wrong)
                await asyncio.sleep(random.uniform(0.05, 0.15))
                # Backspace to fix
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.08, 0.2))

            # Type the correct character
            await self.page.keyboard.press(char)

            # Variable inter-key delay
            if char == " ":
                # Slightly longer pause after space (word boundary)
                await asyncio.sleep(random.uniform(0.12, 0.25))
            elif char in ".,!?":
                # Pause after punctuation
                await asyncio.sleep(random.uniform(0.15, 0.35))
            else:
                await asyncio.sleep(random.uniform(0.04, 0.12))

    async def type_text(self, text: str) -> None:
        """Type text at the current cursor position with human-like timing.

        Same typo simulation as fill() but without clicking an element first.
        """
        typo_rate = random.uniform(0.03, 0.08)

        for char in text:
            if random.random() < typo_rate and char not in ("\n", "\t"):
                wrong = random.choice(
                    string.ascii_lowercase.replace(char.lower(), "")
                )
                await self.page.keyboard.press(wrong)
                await asyncio.sleep(random.uniform(0.05, 0.15))
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.08, 0.2))

            await self.page.keyboard.press(char)
            if char == " ":
                await asyncio.sleep(random.uniform(0.12, 0.25))
            elif char in ".,!?":
                await asyncio.sleep(random.uniform(0.15, 0.35))
            else:
                await asyncio.sleep(random.uniform(0.04, 0.12))

    async def scroll(self, direction: str, amount: int = 3) -> None:
        """Scroll with inertial simulation and random pauses.

        direction: "up" or "down"
        amount: number of scroll steps (each ~300px)
        """
        delta_per_step = 300 if direction == "down" else -300

        for i in range(amount):
            # Inertial: fast at start, slow at end
            progress = i / max(amount - 1, 1)
            # Speed factor: starts at 1.0, decays toward end
            speed = 1.0 - 0.5 * progress

            # Each step is multiple small scrolls for smoothness
            sub_steps = random.randint(3, 6)
            sub_delta = delta_per_step / sub_steps

            for _ in range(sub_steps):
                jitter = random.uniform(-20, 20)
                await self.page.mouse.wheel(0, sub_delta + jitter)
                await asyncio.sleep(random.uniform(0.01, 0.03) / speed)

            # Random pause between major steps
            if random.random() < 0.3:
                await asyncio.sleep(random.uniform(0.3, 0.8))
            else:
                await asyncio.sleep(random.uniform(0.05, 0.15))

        # Occasional slight reverse scroll (human overshoot correction)
        if random.random() < 0.15:
            reverse = -delta_per_step * 0.3
            await self.page.mouse.wheel(0, reverse)

    async def drag(
        self,
        from_x: float,
        from_y: float,
        to_x: float,
        to_y: float,
        *,
        steps: int = 60,
    ) -> None:
        """Drag from one point to another using Bezier curve trajectory.

        Used for slider CAPTCHA: precise horizontal drag with slight Y jitter.
        Does NOT use Humanization.drag_to() (that requires two Locators).
        Uses generate_bezier_points() + manual mouse operations.
        """
        # Move to start position
        await self.page.mouse.move(from_x, from_y)
        await asyncio.sleep(random.uniform(0.05, 0.15))

        # Mouse down
        await self.page.mouse.down()
        await asyncio.sleep(random.uniform(0.1, 0.2))

        # Generate Bezier path
        points = self._h.generate_bezier_points(
            (from_x, from_y), (to_x, to_y), steps=steps
        )

        # Move along path with variable speed and Y jitter
        for i, (x, y) in enumerate(points):
            # Add slight Y jitter (humans don't drag perfectly horizontally)
            y += random.gauss(0, 1.5)
            # Minimal X jitter to stay accurate
            x += random.gauss(0, 0.3)

            await self.page.mouse.move(x, y, steps=1)

            # Variable speed: slow at start and end, fast in middle
            progress = i / len(points)
            if progress < 0.1 or progress > 0.9:
                await asyncio.sleep(random.uniform(0.015, 0.035))
            else:
                await asyncio.sleep(random.uniform(0.005, 0.015))

        # Brief pause before release (human hesitation at target)
        await asyncio.sleep(random.uniform(0.1, 0.3))

        # Mouse up
        await self.page.mouse.up()
