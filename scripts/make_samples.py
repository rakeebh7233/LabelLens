"""Regenerate every sample: labels, manifests, expected results, edge cases and the README.

Run from the repo root:  backend/.venv/bin/python scripts/make_samples.py

Deterministic: fixed seeds and bundled fonts, so running it twice gives identical files.
"""

import csv
import io
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "backend"), str(REPO / "scripts")]

from samples_lib import defects  # noqa: E402
from samples_lib.layouts import LAYOUTS  # noqa: E402
from samples_lib.spec import FIELDS, KNOWN_GAPS, SPECS, Defect, LabelSpec  # noqa: E402

SAMPLES = REPO / "samples"
LABELS = SAMPLES / "labels"
EDGE = SAMPLES / "edge_cases"
MANIFEST_COLUMNS = ["filename", *FIELDS[:4], "government_warning"]


def apply(
    image: np.ndarray, defect: Defect, boxes: dict[str, tuple[int, int, int, int]]
) -> np.ndarray:
    if defect.name == "rotate":
        return defects.rotated(image, defect.amount)
    if defect.name == "perspective":
        return defects.perspective(image, defect.amount)
    if defect.name == "glare":
        return defects.with_glare(image)
    if defect.name == "glare_over_alcohol":
        return defects.glare_over(image, boxes["alcohol"])
    if defect.name == "low_light":
        return defects.low_light(image, seed=int(defect.amount))
    if defect.name == "curved":
        return defects.curved(image, defect.amount)
    raise ValueError(f"unknown defect {defect.name!r}")


def render(spec: LabelSpec) -> np.ndarray:
    canvas = LAYOUTS[spec.layout](spec)
    image = cv2.cvtColor(np.array(canvas.image), cv2.COLOR_RGB2BGR)
    for defect in spec.image_defects:
        image = apply(image, defect, canvas.boxes)
    return image


def write_png(path: Path, image: np.ndarray) -> None:
    ok, data = cv2.imencode(".png", image)
    assert ok
    path.write_bytes(data.tobytes())


def manifest_rows(specs: list[LabelSpec]) -> list[list[str]]:
    rows = []
    for spec in specs:
        app = spec.application
        rows.append([spec.filename, app.brand_name, app.class_type, app.alcohol_content,
                     app.net_contents, ""])  # fmt: skip
    return rows


def write_csv(path: Path, rows: list[list[str]]) -> None:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(MANIFEST_COLUMNS)
    writer.writerows(rows)
    path.write_text(out.getvalue(), encoding="utf-8")


def expected(specs: list[LabelSpec]) -> dict[str, object]:
    return {
        spec.filename: {"overall": spec.expected_overall, "fields": spec.expected_fields}
        for spec in specs
    }


def edge_cases(perfect: np.ndarray) -> list[tuple[str, str, str]]:
    """Files for error handling. Returns (file, purpose, expected behaviour) for the README."""
    EDGE.mkdir(parents=True, exist_ok=True)
    (EDGE / "corrupt.png").write_bytes(b"This is a text file renamed to .png, not an image.\n")
    thumbnail = Image.fromarray(cv2.cvtColor(perfect, cv2.COLOR_BGR2RGB)).resize((300, 400))
    thumbnail.save(EDGE / "unsupported.gif")
    write_png(EDGE / "blank.png", np.full((1600, 1200, 3), 255, np.uint8))
    write_png(EDGE / "orphan_image.png", perfect)
    # Incompressible noise so the PNG is over the 10 MB limit. Gitignored: regenerate it.
    noise = np.random.default_rng(10).integers(0, 256, (2200, 2200, 3), dtype=np.uint8)
    write_png(EDGE / "huge.png", noise)
    return [
        ("corrupt.png", "A text file renamed to .png",
         'Error "This file could not be read as an image"; in a batch the rest carries on'),
        ("unsupported.gif", "Unsupported file type", "Rejected with a plain message (415)"),
        ("huge.png", "Over the 10 MB limit (generated, not committed)",
         "Rejected with a size message (413)"),
        ("blank.png", "A valid image with no text",
         'Every field fails with "not found", plus a hint to check the photo; no crash'),
        ("orphan_image.png", "A photo with no row in applications_with_orphans.csv",
         'Error row "This photo has no row in the spreadsheet"'),
        ("(row) missing_file.png", "A spreadsheet row with no photo",
         'Error row "No photo was uploaded for this spreadsheet row"'),
    ]  # fmt: skip


def contact_sheet(images: dict[str, np.ndarray], columns: int = 6) -> np.ndarray:
    tiles = []
    for name, image in images.items():
        tile = cv2.resize(image, (240, round(image.shape[0] * 240 / image.shape[1])))
        tile = cv2.copyMakeBorder(tile, 0, max(0, 330 - tile.shape[0]), 0, 0,
                                  cv2.BORDER_CONSTANT, value=(255, 255, 255))[:330]  # fmt: skip
        tile = cv2.copyMakeBorder(tile, 30, 6, 6, 6, cv2.BORDER_CONSTANT, value=(60, 60, 60))
        cv2.putText(tile, name[:28], (6, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        tiles.append(tile)
    while len(tiles) % columns:
        tiles.append(np.full_like(tiles[0], 255))
    rows = [np.hstack(tiles[i : i + columns]) for i in range(0, len(tiles), columns)]
    return np.vstack(rows)


def readme(specs: list[LabelSpec], edges: list[tuple[str, str, str]]) -> str:
    def fields(spec: LabelSpec) -> str:
        notes = [f"{name} = {status}" for name, status in spec.expected_fields.items()
                 if status != "pass"]  # fmt: skip
        if not spec.expected_fields:
            return "overall only"
        return ", ".join(notes) if notes else "all pass"

    lines = [
        "# Sample labels",
        "",
        "Generated by `scripts/make_samples.py`; do not edit by hand. Regenerate with:",
        "",
        "```bash",
        "backend/.venv/bin/python scripts/make_samples.py",
        "```",
        "",
        "Every brand, address and label here is fictional. Fonts are the bundled DejaVu fonts",
        "(`scripts/fonts/`, Bitstream Vera licence with DejaVu changes in the public domain; see",
        "`scripts/fonts/LICENSE-DejaVu.txt`). `contact_sheet.png` shows all labels at a glance.",
        "",
        "## Files",
        "",
        "- `labels/`: the label images below.",
        "- `applications.csv`: the batch manifest, one row per label (blank `government_warning`",
        "  means the standard text).",
        "- `applications_with_orphans.csv`: the same plus a row for `missing_file.png`; upload it",
        "  with `edge_cases/orphan_image.png` to see both orphan cases.",
        "- `expected.json`: the expected overall and per-field result for each label, used by",
        "  `backend/tests/test_samples.py`.",
        "- `edge_cases/`: files for error handling (below).",
        "",
        "Statuses: `pass`, `review`, `fail`; `not_fail` means pass or review (a degraded photo of",
        "a good label must never fail), `not_pass` means review or fail (a hidden field must",
        "never pass).",
        "",
        "## Labels",
        "",
        "| # | File | Layout | What is different | Expected | Field notes |",
        "|---|---|---|---|---|---|",
    ]
    for spec in specs:
        lines.append(f"| {spec.id} | `{spec.filename}` | {spec.layout} | {spec.tests} | "
                     f"{spec.expected_overall} | {fields(spec)} |")  # fmt: skip
    lines += [
        "",
        "## Known gaps",
        "",
        "Samples whose expected result the pipeline does not produce yet. The regression test",
        "marks them as expected failures until a decision is made for each.",
        "",
        *[f"- `{name}`: {reason}." for name, reason in KNOWN_GAPS.items()],
        "",
        "## Edge cases (`edge_cases/`)",
        "",
        "| File | Purpose | Expected behaviour |",
        "|---|---|---|",
        *[f"| `{name}` | {purpose} | {behaviour} |" for name, purpose, behaviour in edges],
        "",
        "## Load test",
        "",
        "`scripts/make_load_set.py` copies the passing labels under unique names until there are",
        "250, with a matching manifest, into `samples/load/` (gitignored).",
        "",
        "## Not included",
        "",
        "The spec's optional real-photo supplement (AI-generated or staged bottle photos) is not",
        "included; every image here is rendered by the script.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    if LABELS.exists():
        shutil.rmtree(LABELS)
    LABELS.mkdir(parents=True)
    images: dict[str, np.ndarray] = {}
    for spec in SPECS:
        image = render(spec)
        write_png(LABELS / spec.filename, image)
        images[spec.filename] = image

    rows = manifest_rows(SPECS)
    write_csv(SAMPLES / "applications.csv", rows)
    perfect = SPECS[0]
    orphan_row = [["missing_file.png", *manifest_rows([perfect])[0][1:]]]
    write_csv(SAMPLES / "applications_with_orphans.csv", rows + orphan_row)
    (SAMPLES / "expected.json").write_text(json.dumps(expected(SPECS), indent=2) + "\n")

    edges = edge_cases(images[perfect.filename])
    write_png(SAMPLES / "contact_sheet.png", contact_sheet(images))
    (SAMPLES / "README.md").write_text(readme(SPECS, edges))
    print(f"Wrote {len(SPECS)} labels, manifests, expected.json, {len(edges) - 1} edge case "
          f"files and README to {SAMPLES.relative_to(REPO)}/")  # fmt: skip


if __name__ == "__main__":
    main()
