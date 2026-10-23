# Sample labels

Test labels (good and deliberately bad) and the batch manifest `applications.csv` that matches
them by filename. Not generated yet; see `SAMPLES_SPEC.md`.

| File | What is wrong |
|---|---|
| _to be added_ | |

## `ocr_synthetic/`: OCR pipeline previews

The synthetic images the OCR tests use (`backend/tests/label_images.py`), each next to what the
heavy preprocessing pass makes of it. `contact_sheet.png` shows them all side by side.
Regenerate with `backend/.venv/bin/python scripts/make_ocr_previews.py`.

| Case | Damage |
|---|---|
| 1_clean | none |
| 2_rotated_10, 3_rotated_-7 | rotated 10 and -7 degrees on a canvas grown to fit |
| 4_blurred | Gaussian blur, sigma 2 |
| 5_glare | grey paper with a bright hotspot |
| 6_dim_uneven | shadow darkening toward the right edge |
| 7_rotated_glare | rotation and glare together; a few words at the hotspot centre stay faint because they are fully washed out |
