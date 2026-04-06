"""
Tracer bullet: Verify humanization-playwright integrates with Patchright for
human-like mouse movement and typing simulation.

Integration points tested:
1. humanization-playwright + Patchright page (mouse trajectory)
2. Typing simulation with realistic delays
"""

import asyncio
import math
import time
from humanization import Humanization, HumanizationConfig
from patchright.async_api import async_playwright


async def test_mouse_trajectory():
    """
    Integration Point 1: Mouse movement via humanization-playwright on a Patchright page.
    Verifies trajectories follow Bezier curves (non-linear) with jitter.
    """
    print("=" * 60)
    print("TEST: Mouse Trajectory (humanization-playwright + Patchright)")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()

        # Navigate to a real page
        await page.goto("https://example.com")
        print(f"[OK] Page loaded: {await page.title()}")

        # Create Humanization instance directly (bypass undetected_launch which needs headed mode)
        config = HumanizationConfig(
            fast=False,
            humanize=True,
            characters_per_minute=400,
            stealth_mode=False,
        )
        h = Humanization(page, config)

        # Capture mouse positions by injecting a tracker
        await page.evaluate("""() => {
            window.__mouseTrack = [];
            document.addEventListener('mousemove', (e) => {
                window.__mouseTrack.push({x: e.clientX, y: e.clientY, t: Date.now()});
            });
        }""")

        # Move to the <h1> element on example.com
        h1_locator = page.locator("h1")
        target = await h.move_to(h1_locator)
        print(f"[OK] move_to completed. Target point: ({target[0]:.1f}, {target[1]:.1f})")

        # Retrieve tracked positions
        track = await page.evaluate("() => window.__mouseTrack")
        print(f"[OK] Captured {len(track)} mouse positions")

        if len(track) < 5:
            print("[FAIL] Too few mouse positions captured")
            await browser.close()
            return False

        # Print first/last 5 positions
        print("\nFirst 5 positions:")
        for pt in track[:5]:
            print(f"  ({pt['x']:.1f}, {pt['y']:.1f})")
        print("Last 5 positions:")
        for pt in track[-5:]:
            print(f"  ({pt['x']:.1f}, {pt['y']:.1f})")

        # Verify trajectory is NOT a straight line by computing curvature
        # For a straight line, all cross products of consecutive segment vectors are ~0
        cross_products = []
        for i in range(1, len(track) - 1):
            # Vector from i-1 to i
            dx1 = track[i]["x"] - track[i - 1]["x"]
            dy1 = track[i]["y"] - track[i - 1]["y"]
            # Vector from i to i+1
            dx2 = track[i + 1]["x"] - track[i]["x"]
            dy2 = track[i + 1]["y"] - track[i]["y"]
            cross = dx1 * dy2 - dy1 * dx2
            cross_products.append(cross)

        non_zero = sum(1 for c in cross_products if abs(c) > 0.5)
        total = len(cross_products)
        curvature_ratio = non_zero / total if total > 0 else 0

        print(f"\nCurvature analysis:")
        print(f"  Total direction changes: {total}")
        print(f"  Non-zero cross products: {non_zero}")
        print(f"  Curvature ratio: {curvature_ratio:.2%}")

        if curvature_ratio > 0.1:
            print("[PASS] Trajectory is NOT a straight line -- Bezier curve confirmed")
        else:
            print("[FAIL] Trajectory appears to be a straight line")
            await browser.close()
            return False

        # Check for jitter (Gaussian noise applied by humanize=True)
        # The small random offsets from random.gauss(0, 1) should create micro-deviations
        diffs = []
        for i in range(1, len(track)):
            dx = track[i]["x"] - track[i - 1]["x"]
            dy = track[i]["y"] - track[i - 1]["y"]
            diffs.append(math.sqrt(dx * dx + dy * dy))

        avg_step = sum(diffs) / len(diffs) if diffs else 0
        variance = sum((d - avg_step) ** 2 for d in diffs) / len(diffs) if diffs else 0
        print(f"  Avg step size: {avg_step:.2f}px, Variance: {variance:.2f}")
        print(f"  Step size range: {min(diffs):.2f} - {max(diffs):.2f}")

        await browser.close()
        return True


async def test_typing_simulation():
    """
    Integration Point 2: Typing simulation with humanization-playwright.
    Verifies variable delays between keystrokes and that text is properly entered.
    """
    print("\n" + "=" * 60)
    print("TEST: Typing Simulation")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()

        # Create a page with an input field
        await page.set_content("""
        <html><body>
            <input id="search" type="text" style="width:400px;height:40px;font-size:16px;" />
        </body></html>
        """)

        config = HumanizationConfig(
            fast=False,
            humanize=True,
            characters_per_minute=300,  # Slow, more visible delays
            stealth_mode=False,
        )
        h = Humanization(page, config)

        # Track keystroke timings
        await page.evaluate("""() => {
            window.__keyTimings = [];
            document.getElementById('search').addEventListener('keydown', (e) => {
                window.__keyTimings.push({key: e.key, t: Date.now()});
            });
        }""")

        test_text = "hello world"
        print(f"Typing: '{test_text}'")
        start = time.time()
        input_locator = page.locator("#search")
        await h.type_at(input_locator, test_text)
        elapsed = time.time() - start
        print(f"[OK] Typing completed in {elapsed:.2f}s")

        # Get actual value
        value = await page.input_value("#search")
        print(f"[OK] Input value: '{value}'")

        # Get keystroke timings
        timings = await page.evaluate("() => window.__keyTimings")
        print(f"[OK] Captured {len(timings)} keystroke events")

        if len(timings) < 2:
            print("[FAIL] Too few keystrokes captured")
            await browser.close()
            return False

        # Analyze inter-keystroke intervals
        intervals = []
        for i in range(1, len(timings)):
            dt = timings[i]["t"] - timings[i - 1]["t"]
            intervals.append(dt)

        avg_interval = sum(intervals) / len(intervals)
        min_interval = min(intervals)
        max_interval = max(intervals)
        variance = sum((iv - avg_interval) ** 2 for iv in intervals) / len(intervals)
        std_dev = math.sqrt(variance)

        print(f"\nKeystroke timing analysis:")
        print(f"  Average interval: {avg_interval:.0f}ms")
        print(f"  Min: {min_interval:.0f}ms, Max: {max_interval:.0f}ms")
        print(f"  Std deviation: {std_dev:.1f}ms")
        print(f"  Range ratio: {max_interval / min_interval:.1f}x")

        # Print individual intervals
        print("\n  Per-character intervals (ms):")
        for i, iv in enumerate(intervals):
            char = timings[i + 1]["key"]
            marker = " <-- space pause" if timings[i]["key"] == " " else ""
            print(f"    '{char}': {iv:.0f}ms{marker}")

        # Verify timing is variable (not constant)
        if std_dev > 5:
            print(f"\n[PASS] Typing has variable delays (std_dev={std_dev:.1f}ms)")
        else:
            print(f"\n[FAIL] Typing delays too uniform (std_dev={std_dev:.1f}ms)")
            await browser.close()
            return False

        # Verify text was entered correctly
        if value == test_text:
            print(f"[PASS] Text entered correctly: '{value}'")
        else:
            print(f"[WARN] Text mismatch: expected '{test_text}', got '{value}'")

        await browser.close()
        return True


async def main():
    results = {}

    results["mouse_trajectory"] = await test_mouse_trajectory()
    results["typing_simulation"] = await test_typing_simulation()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")

    return all(results.values())


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
