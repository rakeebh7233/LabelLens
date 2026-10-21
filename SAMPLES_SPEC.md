# Sample Label Generation Spec

Hand this to Claude Code when you reach Phase 8 (or paste it in as the prompt body). It defines
a reproducible set of synthetic test labels, a batch manifest, and a regression test.

## Goals

1. Exercise every comparison rule with at least one passing and one failing example.
2. Cover the stakeholder scenarios: case-only brand difference (Dave), warning defects (Jenny),
   messy photos (Jenny), batch edge cases (Sarah).
3. Be fully reproducible: `python scripts/make_samples.py` regenerates everything from a spec list
   with a fixed random seed. No hand-edited images in `samples/labels/`.
4. Double as the regression suite: a test runs every sample through the verify service and asserts
   the expected overall and per-field status.

## Rules

- All brands and addresses are fictional. Do not use real brand names or real logos.
- Use only fonts with permissive licenses (for example DejaVu, Liberation, or Google OFL fonts
  bundled in `scripts/fonts/`). Record the font licenses in `samples/README.md`.
- Canvas about 1200 x 1600 px, RGB PNG. Vary background color/texture per label so the OCR does
  not overfit to one look.
- Warning text must use the canonical constant imported from the app (`backend/app/extract/warning.py`)
  so the generator and the checker cannot drift. Defect variants are derived from it in code.
- Bold prefix: render "GOVERNMENT WARNING:" with a bold font file and the body with a regular one.

## Script structure

```
scripts/
  make_samples.py          # entry point: builds all labels + manifest + expected.json
  samples_lib/
    spec.py                # dataclass LabelSpec + the list of SPECS
    render.py              # draw a label from a LabelSpec with Pillow
    defects.py             # image-level defects (rotate, perspective, glare, blur, low light, noise)
    layouts.py             # spirits, beer, wine layouts (positions, font sizes, colors)
  fonts/                   # bundled fonts + licenses
samples/
  labels/*.png
  applications.csv         # batch manifest
  expected.json            # filename -> expected overall + per-field statuses
  README.md                # table of every sample and what it tests (generate this too)
backend/tests/test_samples.py
```

`LabelSpec` fields: `id`, `filename`, `layout` (spirits|beer|wine), `label_text` (the values drawn on
the label), `application` (the values entered in the application), `warning_variant`
(`standard|titlecase|reworded|missing_sentence2|absent|prefix_not_bold`), `image_defects` (list of
defect name + parameters), `expected` (overall + per-field).

## Sample matrix

`label_text` is what is printed. `application` is what the agent enters. Where only one value is
shown, they are identical.

| # | File | Layout | What is different | Expected overall | Field notes |
|---|---|---|---|---|---|
| 01 | `01_old_tom_perfect.png` | spirits | Nothing. Brand `OLD TOM DISTILLERY`, class `Kentucky Straight Bourbon Whiskey`, `45% Alc./Vol. (90 Proof)`, `750 mL` | pass | all pass |
| 02 | `02_stones_throw_case.png` | spirits | Label brand `STONE'S THROW`, application `Stone's Throw` | review | brand = review (case only), rest pass |
| 03 | `03_brand_curly_apostrophe.png` | spirits | Label uses curly apostrophe, application uses straight | pass | brand = pass |
| 04 | `04_brand_ocr_like_typo.png` | spirits | Label prints `OLD T0M DISTILLERY` (zero), application `OLD TOM DISTILLERY` | review | brand = review via fuzzy score |
| 05 | `05_wrong_brand.png` | spirits | Label `HARBOR LIGHT`, application `OLD TOM DISTILLERY` | fail | brand = fail |
| 06 | `06_wrong_abv.png` | spirits | Label `40% Alc./Vol. (80 Proof)`, application `45% Alc./Vol. (90 Proof)` | fail | abv = fail |
| 07 | `07_proof_only.png` | spirits | Label prints only `90 PROOF`, application `45% Alc./Vol.` | pass | abv = pass via conversion |
| 08 | `08_wrong_net_contents.png` | spirits | Label `700 mL`, application `750 mL` | fail | net = fail |
| 09 | `09_net_contents_units.png` | spirits | Label `75 cL`, application `750 mL` | pass | net = pass |
| 10 | `10_warning_titlecase.png` | spirits | Prefix printed `Government Warning:` | fail | warning = fail, reason mentions uppercase |
| 11 | `11_warning_reworded.png` | spirits | Sentence (1) paraphrased | fail | warning = fail, diff lists changed words |
| 12 | `12_warning_missing_sentence2.png` | spirits | Sentence (2) absent | fail | warning = fail |
| 13 | `13_warning_absent.png` | spirits | No warning block | fail | warning = fail, "no warning found" |
| 14 | `14_warning_not_bold.png` | spirits | Prefix in regular weight | review (or fail if bold detection implemented and reliable) | warning = review at minimum |
| 15 | `15_warning_tiny_text.png` | spirits | Warning rendered very small | review | warning = review (OCR uncertain, not fail) |
| 16 | `16_beer_label.png` | beer | `Harbor Light Pale Ale`, `5.2% ALC/VOL`, `12 FL OZ`, standard warning | pass | all pass; different layout, different units |
| 17 | `17_wine_label.png` | wine | `Cedar Ridge Cabernet Sauvignon`, `13.5% ALC. BY VOL.`, `750 ML`, plus `CONTAINS SULFITES` | pass | all pass; extra text should not confuse matching |
| 18 | `18_rotated_12deg.png` | spirits | Perfect label rotated 12 degrees | pass | tests deskew |
| 19 | `19_perspective_skew.png` | spirits | Perfect label with perspective warp (photographed at an angle) | pass or review | must not be fail |
| 20 | `20_glare.png` | spirits | White radial glare patch over part of the text | pass or review | must not be fail; no false pass if the glare hides a field |
| 21 | `21_low_light_blur.png` | spirits | Darkened, low contrast, mild Gaussian blur and noise | pass or review | must not be fail; ideally includes a hint to retake the photo |
| 22 | `22_curved_text.png` | spirits | Text bent slightly to mimic a bottle | review | known limitation, document it |

Notes for the generator:

- Defects 18-22 should be applied on top of the perfect label so the only variable is image quality.
- "pass or review" cases assert `status != fail`. Never assert `pass` for a degraded image.
- For 20, add a second variant where glare covers the ABV line completely. Expected: the ABV
  field is `review` or `fail` ("could not read"), never `pass`.

## Non-image cases for error handling (not in the main matrix)

Create these in `samples/edge_cases/` for the API tests and manual demo:

| File | Purpose | Expected behavior |
|---|---|---|
| `corrupt.png` | A text file renamed to `.png` | Row-level error "This file could not be read as an image", batch continues |
| `unsupported.gif` or `.pdf` | Unsupported type | 4xx with a plain-language message |
| `huge.png` | Larger than the configured size limit | Rejected with a clear size message |
| `blank.png` | Valid image, no text | Every field fails with "not found on label", no crash |
| `orphan_image.png` | Image with no manifest row | Reported in pre-upload validation |
| manifest row `missing_file.png` | Row with no image | Reported in pre-upload validation |

## Batch manifest: `samples/applications.csv`

Columns:

```
filename,brand_name,class_type,alcohol_content,net_contents,government_warning
```

- One row per label in the matrix (the `application` values), leave `government_warning` empty to
  mean "use the standard text".
- Include the two orphan cases above in a separate file `samples/applications_with_orphans.csv`
  so the main manifest stays clean.
- Also generate `samples/expected.json`, for example:

```json
{
  "02_stones_throw_case.png": {
    "overall": "review",
    "fields": { "brand_name": "review", "class_type": "pass", "alcohol_content": "pass",
                "net_contents": "pass", "government_warning": "pass" }
  }
}
```

## Load-test helper

Add `scripts/make_load_set.py` that copies the passing samples with unique filenames until it has
250 labels and writes a matching manifest into `samples/load/` (gitignored). Use it to verify the
batch UI, worker pool and the "250 labels" scenario from Sarah.

## Regression test: `backend/tests/test_samples.py`

- Parametrize over `expected.json`.
- Run each image through `verify_label()` with its manifest row.
- Assert overall status and each listed field status. For "pass or review" entries, assert the
  status is not `fail` (store these as `"not_fail"` in `expected.json`).
- Assert `timings_ms.total` is under a generous ceiling (for example 8000 ms) so CI on slow
  machines does not flake, and print the median separately for your README.
- Mark the degraded-image cases with `@pytest.mark.slow` if they push the test time up.

## Real-photo supplement (manual, optional)

The take-home suggests AI image generators. Add 4-6 more realistic images in `samples/photos/`:
a label on a bottle photographed straight on, at an angle, under warm light, with glare, and
a wine back label. These cannot be asserted exactly, so only assert `status != fail` or just
log the results in the README as an informal accuracy check. State clearly in
`samples/README.md` that they are AI-generated or staged and fictional.

## Acceptance criteria

- `python scripts/make_samples.py` is deterministic: running it twice produces identical files.
- `samples/README.md` is generated and lists every sample, what it tests and the expected result.
- `pytest backend/tests/test_samples.py` passes, and a deliberately broken comparison rule
  (for example, disabling the uppercase prefix check) makes at least one sample test fail.
- No sample uses a real brand, logo or copyrighted artwork.

## Prompt to paste into Claude Code

```
Read CLAUDE.md and SAMPLES_SPEC.md. Implement the sample generator exactly as specified:
scripts/make_samples.py with the samples_lib modules, the 22-label matrix, the edge cases,
applications.csv, expected.json, the generated samples/README.md, make_load_set.py, and
backend/tests/test_samples.py.

Start by showing me the LabelSpec dataclass and the first 3 specs, and wait for my OK.
Import the canonical warning text from backend/app/extract/warning.py instead of copying it.
Use fictional brands only and bundled permissive fonts. Run the tests and report which samples
do not yet produce the expected status, so I can decide whether the rule or the sample is wrong.
```
