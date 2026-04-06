"""
Tracer bullet: Verify OpenCV can detect slider CAPTCHA gap positions.

Integration Point 3: OpenCV template matching / edge detection for
identifying the puzzle piece gap in a slider CAPTCHA image.

Uses synthetic test images (numpy-generated) to validate the approach
without needing real CAPTCHA screenshots.
"""

import cv2
import numpy as np


def create_mock_captcha(
    width: int = 400,
    height: int = 200,
    gap_x: int = 280,
    gap_y: int = 60,
    piece_size: int = 60,
) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    """
    Create a synthetic slider CAPTCHA image pair:
    - background: image with a puzzle gap (darker region)
    - piece: the puzzle piece that fits into the gap
    Returns (background, piece, (gap_x, gap_y))
    """
    rng = np.random.RandomState(42)

    # Create a colorful background with gradients and noise
    bg = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        for x in range(width):
            bg[y, x] = [
                int(100 + 80 * np.sin(x / 30.0)),
                int(120 + 60 * np.cos(y / 20.0)),
                int(140 + 50 * np.sin((x + y) / 25.0)),
            ]
    # Add some noise for realism
    noise = rng.randint(0, 20, bg.shape, dtype=np.uint8)
    bg = cv2.add(bg, noise)

    # Extract the puzzle piece before creating the gap
    piece = bg[gap_y : gap_y + piece_size, gap_x : gap_x + piece_size].copy()

    # Add a subtle border to the piece (like real puzzle pieces have)
    cv2.rectangle(piece, (0, 0), (piece_size - 1, piece_size - 1), (200, 200, 200), 2)

    # Create the gap in the background (darker, slightly different)
    gap_region = bg[gap_y : gap_y + piece_size, gap_x : gap_x + piece_size]
    darkened = (gap_region.astype(np.float32) * 0.3).astype(np.uint8)
    bg[gap_y : gap_y + piece_size, gap_x : gap_x + piece_size] = darkened

    # Add gap border (shadow effect)
    cv2.rectangle(
        bg,
        (gap_x, gap_y),
        (gap_x + piece_size, gap_y + piece_size),
        (40, 40, 40),
        2,
    )

    return bg, piece, (gap_x, gap_y)


def detect_gap_template_matching(
    background: np.ndarray, piece: np.ndarray
) -> tuple[int, int, float]:
    """
    Method 1: Template matching.
    Match the puzzle piece against the background to find where it fits.
    """
    bg_gray = cv2.cvtColor(background, cv2.COLOR_BGR2GRAY)
    piece_gray = cv2.cvtColor(piece, cv2.COLOR_BGR2GRAY)

    result = cv2.matchTemplate(bg_gray, piece_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    return max_loc[0], max_loc[1], max_val


def detect_gap_edge_detection(
    background: np.ndarray, piece_size: int = 60
) -> tuple[int, int] | None:
    """
    Method 2: Edge detection + contour analysis.
    Find the dark rectangular gap via Canny edges and contour filtering.
    """
    gray = cv2.cvtColor(background, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)

    # Dilate to connect edge fragments
    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best = None
    best_score = float("inf")

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        # Filter: gap should be roughly square and close to piece_size
        aspect = w / h if h > 0 else 0
        if 0.7 < aspect < 1.4 and 0.5 * piece_size < w < 1.5 * piece_size:
            # Score by how close the contour area matches expected piece area
            area_diff = abs(w * h - piece_size * piece_size)
            if area_diff < best_score:
                best_score = area_diff
                best = (x, y)

    return best


def visualize_results(
    background: np.ndarray,
    piece: np.ndarray,
    actual_gap: tuple[int, int],
    template_result: tuple[int, int],
    edge_result: tuple[int, int] | None,
    piece_size: int,
    output_path: str,
):
    """Save a visualization of detection results."""
    vis = background.copy()
    h, w = vis.shape[:2]

    # Create a canvas with background + piece side by side + annotations
    canvas = np.zeros((h + 120, w + piece_size + 20, 3), dtype=np.uint8)
    canvas[:h, :w] = vis

    # Place piece on the right
    py = (h - piece_size) // 2
    canvas[py : py + piece_size, w + 10 : w + 10 + piece_size] = piece

    # Draw actual gap (green)
    cv2.rectangle(
        canvas,
        actual_gap,
        (actual_gap[0] + piece_size, actual_gap[1] + piece_size),
        (0, 255, 0),
        2,
    )
    cv2.putText(
        canvas,
        "actual",
        (actual_gap[0], actual_gap[1] - 5),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (0, 255, 0),
        1,
    )

    # Draw template match result (blue)
    cv2.rectangle(
        canvas,
        template_result,
        (template_result[0] + piece_size, template_result[1] + piece_size),
        (255, 0, 0),
        2,
    )
    cv2.putText(
        canvas,
        "template",
        (template_result[0], template_result[1] + piece_size + 15),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 0, 0),
        1,
    )

    # Draw edge detection result (red)
    if edge_result:
        cv2.rectangle(
            canvas,
            edge_result,
            (edge_result[0] + piece_size, edge_result[1] + piece_size),
            (0, 0, 255),
            2,
        )
        cv2.putText(
            canvas,
            "edge",
            (edge_result[0] + piece_size + 5, edge_result[1] + piece_size // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 255),
            1,
        )

    # Legend
    y_offset = h + 20
    cv2.putText(canvas, "Legend:", (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(canvas, "Green = Actual gap", (10, y_offset + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
    cv2.putText(canvas, "Blue = Template match", (10, y_offset + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)
    cv2.putText(canvas, "Red = Edge detection", (10, y_offset + 60), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)

    cv2.imwrite(output_path, canvas)


def main():
    print("=" * 60)
    print("TEST: OpenCV Slider CAPTCHA Gap Detection")
    print("=" * 60)

    piece_size = 60
    actual_gap_x, actual_gap_y = 280, 60

    # Generate synthetic CAPTCHA
    bg, piece, (gx, gy) = create_mock_captcha(
        gap_x=actual_gap_x, gap_y=actual_gap_y, piece_size=piece_size
    )
    print(f"[OK] Generated mock CAPTCHA: bg={bg.shape}, piece={piece.shape}")
    print(f"     Actual gap position: ({gx}, {gy})")

    # Method 1: Template matching
    print("\n--- Method 1: Template Matching ---")
    tx, ty, confidence = detect_gap_template_matching(bg, piece)
    template_error = abs(tx - gx) + abs(ty - gy)
    print(f"  Detected: ({tx}, {ty}), confidence: {confidence:.4f}")
    print(f"  Error from actual: {template_error}px (manhattan)")

    if template_error < piece_size * 0.3:
        print(f"  [PASS] Template matching accurate within {piece_size * 0.3:.0f}px threshold")
        template_pass = True
    else:
        print(f"  [FAIL] Template matching too far off")
        template_pass = False

    # Method 2: Edge detection
    print("\n--- Method 2: Edge Detection ---")
    edge_result = detect_gap_edge_detection(bg, piece_size)
    if edge_result:
        ex, ey = edge_result
        edge_error = abs(ex - gx) + abs(ey - gy)
        print(f"  Detected: ({ex}, {ey})")
        print(f"  Error from actual: {edge_error}px (manhattan)")
        if edge_error < piece_size * 0.5:
            print(f"  [PASS] Edge detection accurate within {piece_size * 0.5:.0f}px threshold")
            edge_pass = True
        else:
            print(f"  [FAIL] Edge detection too far off")
            edge_pass = False
    else:
        print("  [FAIL] Edge detection found no suitable contour")
        edge_result = (0, 0)
        edge_pass = False

    # Test with different gap positions to verify robustness
    print("\n--- Robustness: Multiple gap positions ---")
    positions = [(100, 40), (200, 80), (300, 50), (150, 100)]
    template_successes = 0
    for pos_x, pos_y in positions:
        bg2, piece2, _ = create_mock_captcha(gap_x=pos_x, gap_y=pos_y, piece_size=piece_size)
        tx2, ty2, conf2 = detect_gap_template_matching(bg2, piece2)
        err = abs(tx2 - pos_x) + abs(ty2 - pos_y)
        status = "OK" if err < piece_size * 0.3 else "MISS"
        print(f"  Gap({pos_x},{pos_y}) -> Detected({tx2},{ty2}), err={err}px, conf={conf2:.3f} [{status}]")
        if err < piece_size * 0.3:
            template_successes += 1

    print(f"\n  Template matching: {template_successes}/{len(positions)} positions correct")

    # Save visualization
    output_path = "/tmp/captcha-analysis.png"
    visualize_results(
        bg, piece, (gx, gy), (tx, ty), edge_result, piece_size, output_path
    )
    print(f"\n[OK] Visualization saved to {output_path}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Template matching: {'PASS' if template_pass else 'FAIL'}")
    print(f"  Edge detection:    {'PASS' if edge_pass else 'FAIL'}")
    print(f"  Robustness:        {template_successes}/{len(positions)}")

    return template_pass  # Template matching is the primary method


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
