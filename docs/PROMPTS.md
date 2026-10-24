# LabelLens Prompt Library

How to use: put `CLAUDE.md` in the repo root so Claude Code loads it automatically. Then paste
the prompts below **one at a time, in order**. Review and run the tests after each one before
moving on. Each prompt lists acceptance criteria so you know when it is done.

Tip: start each new session with `Read CLAUDE.md and summarize the plan back to me in 5 bullets`
to confirm it has the context. Use plan mode for Phases 1, 4 and 7.

---

## Phase 0: Scaffold

```
Read CLAUDE.md. Scaffold the LabelLens repo exactly as described in the layout section.

- Backend: FastAPI app with a /api/health endpoint, config.py reading env vars, a pyproject.toml
  or requirements.txt (fastapi, uvicorn, pydantic, pytesseract, opencv-python-headless,
  rapidfuzz, python-multipart, pytest, httpx), and an empty tests/ with one passing smoke test.
- Frontend: Vite + React + TypeScript + Tailwind, with a placeholder page.
- Add a .gitignore, a Makefile (or scripts) with `make dev`, `make test`, `make build`.
- Do not implement features yet.

Acceptance: backend starts and /api/health returns 200; frontend dev server renders; `make test` passes.
```

## Phase 1: Domain model and schemas

```
Define the Pydantic schemas in backend/app/schemas.py for the domain in CLAUDE.md:

- ApplicationData: brand_name, class_type, alcohol_content, net_contents, government_warning (optional, defaults to the standard text).
- Status enum: pass, review, fail.
- FieldResult: field, status, expected, found, reason (plain English), confidence (0-1).
- LabelResult: label_id/filename, overall_status (worst field), fields, timings_ms, warnings (e.g. low image quality).
- BatchJob / BatchProgress models.

Include a helper that computes overall_status. Write unit tests for it. Keep reasons human readable.

Acceptance: schemas import cleanly, tests pass, overall_status picks the worst status.
```

## Phase 2: Text normalization and parsers (pure logic, test heavily)

```
Implement backend/app/matching/normalize.py and parsers.py. These are pure functions.

normalize: casefold, unicode normalization, curly vs straight quotes/apostrophes, collapse whitespace, strip punctuation noise, common OCR confusions handled conservatively (e.g. 0/O, 1/l only inside matching, never rewrite displayed text).

parsers:
- parse_abv("45% Alc./Vol. (90 Proof)") -> abv_percent=45.0, proof=90.0. Handle "45%", "45 % ABV", "90 Proof", "Alc 45% by vol".
- parse_net_contents("750 mL") -> 750 mL. Handle "750ml", "75 cL", "1 L", "25.4 FL OZ", "1.75L". Convert to mL for comparison.

Write a thorough pytest table of cases, including malformed input returning None rather than raising.

Acceptance: all cases pass; parsers never raise on garbage input.
```

## Phase 3: Comparison rules

```
Implement backend/app/matching/compare.py returning FieldResult for each field.

Rules:
- Brand and class/type: exact after normalization -> pass; differs only by case/punctuation/spacing -> review with a reason that names the difference; rapidfuzz ratio >= 90 -> review; otherwise fail. Tune thresholds in config.
- Alcohol content: compare parsed numbers. Equal ABV, or ABV consistent with proof (proof == 2 x ABV) -> pass. If label has only proof and application only ABV (or vice versa), convert and compare. Mismatch -> fail.
- Net contents: compare in mL; equal -> pass; unparseable -> review.
- Include the "STONE'S THROW" vs "Stone's Throw" case as a named test.
- Low OCR confidence downgrades pass -> review, never to fail by itself.

Acceptance: table-driven tests for each field, thresholds configurable, reasons read naturally.
```

## Phase 4: Government warning (the most important rule)

```
Implement backend/app/extract/warning.py.

1. Locate the warning block in OCR text (tolerate line breaks, hyphenation at line ends, and minor OCR noise when locating, but not when judging).
2. Compare to the canonical text word for word after whitespace normalization.
   - Any wording difference -> fail, and the reason lists the differing words (diff).
   - Prefix "GOVERNMENT WARNING:" not fully uppercase (e.g. "Government Warning:") -> fail with that exact reason.
   - Missing colon -> fail.
   - Not found at all -> fail ("No government warning statement found").
   - OCR damage in only a few characters of an otherwise matching text -> review, not fail, and show which characters are uncertain.
3. Expose the canonical text as a constant in one place.

Write tests for: exact match, title-case prefix, missing sentence (2), reworded sentence (1), line-wrapped text, minor OCR noise, absent warning.

Acceptance: the title-case case fails with a clear reason; the OCR-noise case returns review.
```

## Phase 5: OCR engine and preprocessing

```
Implement backend/app/ocr/engine.py and preprocess.py.

- OcrEngine interface: run(image) -> OcrResult (text, words with bounding boxes and confidences, mean confidence).
- TesseractEngine implementation via pytesseract using image_to_data. Use a sensible psm (try 6 and 11) and pick the better result by mean confidence only if the first is low.
- preprocess: cap long edge at ~1600px, grayscale, CLAHE contrast; conditional extras when confidence is low: deskew (via minAreaRect/Hough), glare reduction (clip highlights, inpaint), adaptive threshold. Return which steps were applied so we can show it.
- Time each stage.

Add tests using generated images (render text with Pillow, then rotate/blur/add glare) asserting the pipeline improves or preserves recognition of the brand name.

Acceptance: a clean label is read in well under 3 seconds; a rotated 10-degree label is still read correctly.
```

## Phase 6: Field extraction and the verify service

```
Implement backend/app/extract/fields.py and services/verify.py.

- Given OcrResult text/words, produce candidate values for brand, class/type, ABV, net contents. Use heuristics: ABV via regex, net contents via regex, brand as the most prominent text (largest word height near the top), class/type via a known-type vocabulary (whiskey, bourbon, vodka, gin, rum, tequila, wine, beer, ale, etc.) with fuzzy fallback.
- Better approach where possible: instead of guessing the brand, search the OCR text for the *expected* value and score the best matching span. Verification is "is the expected value on the label", which is easier and more robust than free extraction.
- verify.py orchestrates: preprocess -> OCR once -> compare each field -> LabelResult with timings_ms. Catch per-stage failures and return a helpful error result instead of raising.

Acceptance: sample Old Tom Distillery label (CLAUDE.md fields) returns pass on every field; total under 5s locally.
```

## Phase 7: API

```
Add FastAPI routes:

- POST /api/verify  (multipart: image + application fields) -> LabelResult
- POST /api/batch   (multipart: images[] + manifest.csv) -> {job_id}
- GET  /api/batch/{job_id} -> progress + results so far
- GET  /api/batch/{job_id}/export.csv
- GET  /api/health

Validation: allowed types (jpg, png, webp, tiff), max file size, max batch size (configurable, default 300), helpful 4xx messages. Batch uses a bounded worker pool (ThreadPool/ProcessPool, since OCR is CPU bound), per-label error isolation, and an in-memory job store with TTL cleanup. Uploaded files are deleted after processing.

Add API tests with httpx/TestClient, including: bad file type, corrupt image, manifest row with no matching image, image with no manifest row, one bad file inside a batch of 10.

Acceptance: all tests pass; a 20-label batch completes and reports progress.
```

## Phase 8: Sample data

```
Create the samples/ folder.

- Write a Python script scripts/make_samples.py that renders synthetic label images with Pillow (several fonts, backgrounds) from a spec list, so they are reproducible. Include a good label and deliberate defects:
  1. perfect label (Old Tom Distillery)
  2. brand case difference (Stone's Throw)
  3. wrong ABV
  4. wrong net contents
  5. title-case "Government Warning:"
  6. reworded warning
  7. missing warning
  8. rotated 12 degrees
  9. glare patch / low contrast
  10. a beer label and a wine label with different layouts
- Generate samples/applications.csv for batch use and samples/README.md describing the expected outcome of each file.
- Add a test that runs every sample through verify and asserts the expected overall status.

Acceptance: `python scripts/make_samples.py` regenerates everything; the sample test passes.
```

## Phase 9: Frontend, single label

```
Build the Verify page. Read the UX rules in CLAUDE.md (73-year-old test).

- One big drag-and-drop area with a visible "Choose a file" button fallback. Image preview after selection.
- A simple form with 5 clearly labelled fields (the warning field is prefilled with the standard text and collapsed behind "Edit warning text").
- One large primary button: "Check this label". Disabled until an image and required fields exist, with text explaining why.
- Results: big overall banner (Pass / Needs review / Fail) with icon + text, then a card per field showing "Application says" vs "Label says" side by side and the reason in plain English. Review/fail items expanded by default.
- Loading state with a spinner and "Reading the label...", friendly error states (unreadable image, server error, network error) with a retry button.
- Show the elapsed time quietly in the footer of the result.

Add component tests for the result card and form validation.

Acceptance: usable with keyboard only; passes a manual screen-reader label check; looks clean at 1280px and 390px width.
```

## Phase 10: Frontend, batch

```
Build the Batch page.

- Step layout: 1) drop images (or a folder), 2) drop the CSV manifest (offer "Download CSV template"), 3) "Start checking".
- Validate before upload: list images without a manifest row and rows without an image, in plain language, with the option to continue with the matches.
- Progress bar with "42 of 250 checked", and a table that fills in as labels finish: filename, brand, overall status badge, and the number of issues. Sort fails first by default; filter chips (All / Fail / Review / Pass); search box.
- Click a row to open the same detail view as the single-label page in a side panel.
- "Download results (CSV)" button.
- Poll the job endpoint every second or two; handle cancel and page refresh (store job_id in the URL).

Acceptance: a 50-label sample batch shows live progress, the table is usable while running, and one corrupt file shows a row-level error without stopping the batch.
```

## Phase 11: Containerize and deploy

```
Write the Dockerfile (multi-stage: build the frontend, then a python:3.11-slim image that apt-installs tesseract-ocr and libgl-free OpenCV deps, copies the built frontend, and serves it from FastAPI). Add docker-compose.yml for local runs, a /api/health healthcheck, and PORT env support.

Provide deployment instructions for Render (or Fly.io) in the README. Pick instance sizing that meets the 5-second target and note it. Add a startup self-test that logs whether tesseract is available.

Acceptance: `docker compose up` serves the whole app on one port; the app works end to end with the sample labels.
```

## Phase 12: Bold detection (optional, only if time remains)

```
Implement extract/boldness.py: given the image and the bounding boxes of the warning prefix words vs the rest of the warning, estimate stroke width (distance transform on the binarized region, median stroke width normalized by x-height). Treat the prefix as bold if its normalized stroke width is meaningfully greater than the body text.

Return one of: bold, not_bold, unknown. unknown (tiny text, low resolution) yields review, never fail. Test with Pillow-rendered bold vs regular fonts. Record the heuristic's limitations in docs/DECISIONS.md.

Acceptance: correct on the synthetic bold/regular set; returns unknown instead of guessing on very small text.
```

## Phase 13: Documentation

```
Write README.md for evaluators: what it is, a screenshot placeholder, live URL placeholder, quick start (Docker, and local dev), how to run tests, how to generate samples, API overview, and a section "How I approached this" mapping each stakeholder concern to a design decision (5-second target -> local OCR + single pass; firewall -> no cloud dependency; Dave -> three-state results; Jenny -> exact warning check; Sarah -> simple UI + batch).

Write docs/DECISIONS.md with: tool choices and alternatives considered, assumptions (no COLA integration, no PII stored, in-memory jobs), known limitations (bold detection heuristic, handwriting/stylized fonts, curved bottle text, non-English labels), and "what I would do next" (persistent queue, auth, retention policy, fine-tuned detector, LLM fallback on an allowlisted endpoint).

Keep it honest and concise.
```

---

## Reusable utility prompts

**Plan before coding**

```
Before writing code, propose a plan for <task> in under 15 lines: files to touch, new functions, tests, and risks. Wait for my approval.
```

**Add tests**

```
Review <file>. List the edge cases not yet covered, then add pytest tests for them. Do not change the implementation unless a test reveals a real bug; if so, explain it first.
```

**Debug**

```
<paste error or describe behavior>. Find the root cause before changing anything. Explain it in two sentences, show the minimal fix, and add a regression test.
```

**Performance check**

```
Profile the single-label path on samples/labels using the timings_ms output. Show a per-stage breakdown over 20 runs (median and p95). If the median exceeds 5 seconds, propose the smallest change that fixes the biggest stage, then re-measure.
```

**Code review**

```
Act as a strict reviewer for a take-home evaluation. Review the diff against CLAUDE.md for: correctness, readability, error handling, naming, dead code, missing tests, and UX copy a non-technical user might not understand. Return a prioritized list; do not edit.
```

**Plain-language UX copy pass**

```
List every user-facing string in the frontend. Rewrite any that contain jargon, blame the user, or exceed one short sentence. Keep tone calm and direct (reading level around grade 7).
```

**Final pre-submission checklist**

```
Run through the submission checklist: fresh clone builds with the README steps only; tests pass; sample regeneration works; Docker image runs; deployed URL works with the sample labels; no secrets committed; README documents trade-offs and limitations. Report anything failing.
```
