"""
Tracer bullet: Validate Snapshot Refs system and iframe element interaction.

Experiments:
1. Ref generation (data-ref injection via JS) and resolution (locator by attribute)
2. iframe element enumeration and interaction via frame_locator
3. Ref invalidation after navigation

Must use patchright.async_api and channel='chrome' per project constraints.
"""

import asyncio
import sys
from pathlib import Path

from patchright.async_api import async_playwright

FIXTURES = Path(__file__).parent / "fixtures"
REFS_PAGE = FIXTURES / "refs_test.html"

# JS to enumerate interactive elements and assign data-ref attributes.
# Returns mapping: {"@e1": {"tag": "button", "text": "Submit", ...}, ...}
ASSIGN_REFS_JS = """() => {
    const selectors = 'a, button, input, select, textarea, [role="button"]';
    const els = document.querySelectorAll(selectors);
    const mapping = {};
    let idx = 1;
    for (const el of els) {
        const ref = '@e' + idx;
        el.setAttribute('data-ref', ref);
        const tag = el.tagName.toLowerCase();
        const text = el.textContent?.trim().slice(0, 80) || '';
        const type = el.getAttribute('type') || '';
        const name = el.getAttribute('name') || '';
        const id = el.id || '';
        mapping[ref] = { tag, text, type, name, id };
        idx++;
    }
    return mapping;
}"""


def result(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    return passed


async def experiment_1(page):
    """Ref generation and resolution: assign data-ref, resolve via locator, interact."""
    print("\n=== Experiment 1: Ref generation and resolution ===")
    all_pass = True

    # Step 1: Assign refs
    mapping = await page.evaluate(ASSIGN_REFS_JS)
    all_pass &= result(
        "Ref assignment",
        len(mapping) > 0,
        f"{len(mapping)} elements tagged: {list(mapping.keys())}",
    )

    # Print mapping for inspection
    for ref, info in mapping.items():
        print(f"    {ref}: <{info['tag']}> id={info.get('id','')} text={info.get('text','')[:30]}")

    # Step 2: Find the submit button ref (id=btn-submit)
    btn_ref = None
    for ref, info in mapping.items():
        if info.get("id") == "btn-submit":
            btn_ref = ref
            break

    all_pass &= result("Find button ref", btn_ref is not None, f"btn-submit → {btn_ref}")

    if btn_ref:
        # Step 3: Resolve ref to locator and click
        locator = page.locator(f'[data-ref="{btn_ref}"]')
        count = await locator.count()
        all_pass &= result("Locator resolves", count == 1, f"count={count}")

        await locator.click()
        click_result = await page.locator("#click-result").inner_text()
        all_pass &= result("Click via ref works", click_result == "clicked", f"result={click_result!r}")

    # Step 4: Find input ref and fill
    input_ref = None
    for ref, info in mapping.items():
        if info.get("id") == "input-name":
            input_ref = ref
            break

    all_pass &= result("Find input ref", input_ref is not None, f"input-name → {input_ref}")

    if input_ref:
        locator = page.locator(f'[data-ref="{input_ref}"]')
        await locator.fill("tracer-test-value")
        value = await locator.input_value()
        all_pass &= result("Fill via ref works", value == "tracer-test-value", f"value={value!r}")

    # Step 5: Verify role="button" element got a ref
    role_ref = None
    for ref, info in mapping.items():
        if info.get("id") == "div-btn":
            role_ref = ref
            break

    all_pass &= result("Role button ref assigned", role_ref is not None, f"div-btn → {role_ref}")

    if role_ref:
        locator = page.locator(f'[data-ref="{role_ref}"]')
        await locator.click()
        role_result = await page.locator("#role-result").inner_text()
        all_pass &= result("Role button click via ref", role_result == "role-clicked", f"result={role_result!r}")

    return all_pass


async def experiment_2(page):
    """iframe element enumeration and interaction via refs."""
    print("\n=== Experiment 2: iframe element enumeration and interaction ===")
    all_pass = True

    # Step 1: Enumerate frames
    frames = page.frames
    all_pass &= result("Frame enumeration", len(frames) > 1, f"{len(frames)} frames found")

    for i, frame in enumerate(frames):
        print(f"    frame[{i}]: name={frame.name!r} url={frame.url[:60]}")

    # Step 2: Find the iframe frame (srcdoc iframe has special URL)
    iframe_frame = None
    for frame in frames:
        if frame != page.main_frame:
            iframe_frame = frame
            break

    all_pass &= result("Iframe frame found", iframe_frame is not None)

    if iframe_frame:
        # Step 3: Assign refs inside iframe via frame.evaluate()
        iframe_mapping = await iframe_frame.evaluate(ASSIGN_REFS_JS)
        all_pass &= result(
            "Iframe ref assignment",
            len(iframe_mapping) > 0,
            f"{len(iframe_mapping)} elements: {list(iframe_mapping.keys())}",
        )

        for ref, info in iframe_mapping.items():
            print(f"    {ref}: <{info['tag']}> id={info.get('id','')} text={info.get('text','')[:30]}")

        # Step 4: Interact with iframe element using frame_locator
        iframe_btn_ref = None
        for ref, info in iframe_mapping.items():
            if info.get("id") == "iframe-btn":
                iframe_btn_ref = ref
                break

        all_pass &= result("Find iframe button ref", iframe_btn_ref is not None, f"iframe-btn → {iframe_btn_ref}")

        if iframe_btn_ref:
            # Method A: frame_locator('iframe').locator('[data-ref="@eN"]')
            fl = page.frame_locator("#test-iframe")
            locator_a = fl.locator(f'[data-ref="{iframe_btn_ref}"]')

            try:
                await locator_a.click(timeout=5000)
                click_result = await iframe_frame.locator("#iframe-result").inner_text()
                all_pass &= result(
                    "frame_locator().locator() click",
                    click_result == "iframe-clicked",
                    f"result={click_result!r}",
                )
            except Exception as e:
                all_pass &= result("frame_locator().locator() click", False, str(e))

        # Step 5: Fill iframe input via frame_locator
        iframe_input_ref = None
        for ref, info in iframe_mapping.items():
            if info.get("id") == "iframe-input":
                iframe_input_ref = ref
                break

        if iframe_input_ref:
            fl = page.frame_locator("#test-iframe")
            locator_input = fl.locator(f'[data-ref="{iframe_input_ref}"]')

            try:
                await locator_input.fill("iframe-tracer-value")
                value = await locator_input.input_value()
                all_pass &= result(
                    "frame_locator().locator() fill",
                    value == "iframe-tracer-value",
                    f"value={value!r}",
                )
            except Exception as e:
                all_pass &= result("frame_locator().locator() fill", False, str(e))

    # Step 6: Unified ref numbering — verify main page and iframe refs don't collide
    # In real implementation, daemon would assign refs across all frames with a single counter.
    # Here we just verify both mappings work independently.
    print("  [INFO] Main page and iframe ref namespaces are independent in this test.")
    print("         Production impl: daemon assigns refs with a single counter across all frames.")

    return all_pass


async def experiment_3(page):
    """Ref invalidation after navigation."""
    print("\n=== Experiment 3: Ref invalidation after navigation ===")
    all_pass = True

    # Step 1: Verify refs exist on current page
    has_refs = await page.evaluate("""() => {
        return document.querySelectorAll('[data-ref]').length;
    }""")
    all_pass &= result("Refs exist before navigation", has_refs > 0, f"{has_refs} refs on page")

    # Step 2: Navigate to a different page (about:blank)
    await page.goto("about:blank")
    await page.wait_for_load_state("domcontentloaded")

    # Step 3: Check refs are gone
    has_refs_after = await page.evaluate("""() => {
        return document.querySelectorAll('[data-ref]').length;
    }""")
    all_pass &= result("Refs gone after navigation", has_refs_after == 0, f"{has_refs_after} refs remain")

    # Step 4: Try to use old ref locator — should find 0 elements
    locator = page.locator('[data-ref="@e1"]')
    count = await locator.count()
    all_pass &= result("Old ref locator finds nothing", count == 0, f"count={count}")

    return all_pass


async def main():
    print("Tracer Bullet: Snapshot Refs + iframe Interaction")
    print(f"Test page: {REFS_PAGE}")

    if not REFS_PAGE.exists():
        print(f"FATAL: {REFS_PAGE} not found")
        sys.exit(1)

    file_url = f"file://{REFS_PAGE.resolve()}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            channel="chrome",
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        # Navigate to test page
        await page.goto(file_url, wait_until="domcontentloaded")
        # Wait for iframe to load
        await page.wait_for_timeout(1000)

        results = {}

        # Experiment 1: Ref generation and resolution
        results["exp1"] = await experiment_1(page)

        # Experiment 2: iframe (need to re-navigate since exp1 doesn't disturb page)
        results["exp2"] = await experiment_2(page)

        # Experiment 3: Ref invalidation (navigates away — must be last)
        results["exp3"] = await experiment_3(page)

        await browser.close()

    # Summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    names = {
        "exp1": "Ref generation + resolution",
        "exp2": "iframe enumeration + interaction",
        "exp3": "Ref invalidation on navigation",
    }
    all_pass = True
    for key, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {names[key]}")
        all_pass &= passed

    print()
    if all_pass:
        print("ALL EXPERIMENTS PASSED")
    else:
        print("SOME EXPERIMENTS FAILED")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    asyncio.run(main())
