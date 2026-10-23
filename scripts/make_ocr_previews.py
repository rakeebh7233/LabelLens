"""Render the synthetic OCR test images and what the heavy preprocessing pass makes of them.

Writes to samples/ocr_synthetic/: one input PNG and one "_after_heavy" PNG per case, plus
contact_sheet.png showing them side by side. These are the same images the OCR tests use
(backend/tests/label_images.py), so the output shows exactly what the tests see.

Run from the repo root:  backend/.venv/bin/python scripts/make_ocr_previews.py
"""

import sys
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.ocr import preprocess  # noqa: E402
from tests.label_images import (  # noqa: E402
    blurred,
    dim_and_uneven,
    render_label,
    rotated,
    with_glare,
)

OUT = REPO / "samples" / "ocr_synthetic"
CASES: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "1_clean": lambda image: image,
    "2_rotated_10": lambda image: rotated(image, 10),
    "3_rotated_-7": lambda image: rotated(image, -7),
    "4_blurred": blurred,
    "5_glare": with_glare,
    "6_dim_uneven": dim_and_uneven,
    "7_rotated_glare": lambda image: with_glare(rotated(image, 10)),
}
_TILE_WIDTH, _TILE_HEIGHT = 400, 560


def _tile(image: np.ndarray, caption: str) -> np.ndarray:
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    height = round(image.shape[0] * _TILE_WIDTH / image.shape[1])
    image = cv2.resize(image, (_TILE_WIDTH, height))
    pad = max(0, _TILE_HEIGHT - height)
    image = cv2.copyMakeBorder(image, 0, pad, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    image = image[:_TILE_HEIGHT]
    image = cv2.copyMakeBorder(image, 40, 6, 6, 6, cv2.BORDER_CONSTANT, value=(60, 60, 60))
    cv2.putText(image, caption, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return image


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    clean = render_label()
    pairs: list[np.ndarray] = []
    for name, damage in CASES.items():
        image = damage(clean)
        fixed = preprocess.heavy(preprocess.basic(image, 1600).image).image
        cv2.imwrite(str(OUT / f"{name}.png"), image)
        cv2.imwrite(str(OUT / f"{name}_after_heavy.png"), fixed)
        pairs.append(np.hstack([_tile(image, f"{name} (input)"), _tile(fixed, "after heavy pass")]))

    if len(pairs) % 2:
        pairs.append(np.full_like(pairs[0], 255))
    rows = [np.hstack(pairs[i : i + 2]) for i in range(0, len(pairs), 2)]
    cv2.imwrite(str(OUT / "contact_sheet.png"), np.vstack(rows))
    print(f"Wrote {2 * len(CASES) + 1} images to {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
