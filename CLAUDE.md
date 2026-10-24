# LabelLens: AI-Assisted Alcohol Label Verification

Standalone prototype for TTB compliance agents. An agent supplies a label image plus the
application data; the tool reads the label with OCR and reports, field by field, whether the
label matches the application.

This is a take-home project. A working core with clean code beats ambitious but unfinished
features. Document every trade-off and limitation.

## Users and what they said (these drive the design)

- **Sarah (Deputy Director):** Results in about 5 seconds or nobody uses it (a past vendor
  pilot took 30-40s and was abandoned). UI must be usable by a 73-year-old: clean, obvious, no
  hunting for buttons. Batch upload of 200-300 labels is a major want.
- **Marcus (IT):** Standalone prototype, no COLA integration. The network firewall blocks many
  outbound domains, so do NOT depend on a cloud AI API. No sensitive data stored.
- **Dave (senior agent):** Judgment matters. "STONE'S THROW" vs "Stone's Throw" is obviously the
  same brand. Do not hard-fail trivial differences; surface them for review.
- **Jenny (junior agent):** The government warning must be exact, word for word. The
  "GOVERNMENT WARNING:" prefix must be ALL CAPS and bold. Title case ("Government Warning") is
  a rejection. Stretch goal: tolerate imperfect photos (angle, glare, bad lighting).

## Fields to verify

| Field | Rule |
|---|---|
| Brand name | Normalized fuzzy match (case, punctuation, whitespace tolerant) |
| Class/type | Normalized fuzzy match |
| Alcohol content | Parse the number and the proof if present; compare numerically (45% == 90 proof) |
| Net contents | Parse value and unit; normalize units (750 mL == 750ml == 75 cL) |
| Government warning | Exact text after whitespace normalization; prefix must be uppercase; bold checked by heuristic |

Optional extras if time allows: bottler name/address, country of origin.

Standard warning text:

> GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic
> beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic
> beverages impairs your ability to drive a car or operate machinery, and may cause health
> problems.

## Result model: three states, never binary

- `pass`: matches after normalization with an identical or trivially different value.
- `review`: likely the same but differs in a judgment-call way (case only, punctuation, high
  fuzzy score, low OCR confidence, bold unverifiable). The agent decides.
- `fail`: clear mismatch, field missing, warning text differs, or prefix not uppercase.

Overall label status = the worst field status. Every non-pass result carries a plain-English
reason an agent can read in one glance (for example: `Label says "Stone's Throw", application says
"STONE'S THROW" - differs only in capitalization`).

## Tech stack

- **Backend:** Python 3.11+, FastAPI, Pydantic v2, uvicorn
- **OCR:** Tesseract via pytesseract (local only, no outbound calls). Keep the engine behind an
  interface so RapidOCR/PaddleOCR can be swapped in.
- **Image preprocessing:** OpenCV (resize cap, grayscale, contrast/CLAHE, deskew, glare handling)
- **Matching:** rapidfuzz plus our own normalization and parsing rules
- **Frontend:** React + Vite + TypeScript + Tailwind
- **Tests:** pytest (backend), Vitest + Testing Library (frontend)
- **Deploy:** single Docker image (installs the tesseract-ocr system package), hosted on Render
  or Fly.io, serving the built frontend from FastAPI so there is one public URL

An optional LLM vision fallback may exist behind an environment flag. It is OFF by default and
must be documented as likely blocked by the agency firewall.

## Repository layout

```
labellens/
  CLAUDE.md
  README.md                 # setup, run, approach, assumptions, limitations
  docs/DECISIONS.md         # trade-offs and why
  docs/PROMPTS.md           # phase-by-phase prompt library
  Dockerfile
  docker-compose.yml
  backend/
    app/
      main.py               # FastAPI app, routes, static frontend mount
      config.py             # env-driven settings
      schemas.py            # Pydantic request/response models
      ocr/
        engine.py           # OcrEngine interface + Tesseract implementation
        preprocess.py       # OpenCV pipeline
      extract/
        fields.py           # find candidate values in OCR text
        warning.py          # warning locate + exact compare
        boldness.py         # stroke-width bold heuristic
      matching/
        normalize.py        # text normalization
        parsers.py          # ABV/proof and net contents parsing
        compare.py          # per-field comparison -> FieldResult
      services/
        verify.py           # orchestrates one label
        batch.py            # parallel batch runner + job store
    tests/
  frontend/
    src/
      components/           # DropZone, FieldForm, ResultCard, BatchTable, StatusBadge
      pages/                # Verify, Batch
      api/                  # typed API client
  samples/
    labels/                 # good and deliberately bad test labels
    applications.csv        # batch manifest matching the sample labels
    README.md               # what is wrong with each bad sample
```

## Performance budget

Target under 5 seconds for a single label on a normal laptop or small cloud instance.
- Downscale images to a max long edge (about 1600px) before OCR.
- Run OCR once per image and reuse the result for every field.
- Preprocess conditionally; run the heavier fix-ups only when OCR confidence is low.
- Log per-stage timings in the response (`timings_ms`) so the budget is verifiable.

## Batch design

- Input: multiple images plus a CSV manifest (filename + application fields). Matching by
  filename keeps it simple and works for importers who already have a spreadsheet.
- Process with a bounded worker pool; report progress per label; stream or poll results so the
  table fills in as labels finish. One bad file must never fail the whole batch.
- Output: sortable/filterable table (fails first), plus CSV export of results.

## Conventions

- Type hints everywhere in Python; TypeScript strict mode in the frontend.
- Small, pure functions for normalization, parsing and comparison. These carry the business
  logic and need thorough unit tests.
- No global mutable state except the batch job store, which sits behind a small class.
- Errors: user-facing messages in plain language (unreadable image, unsupported file type,
  file too large, missing field). Never show stack traces in the UI.
- Accessibility: large click targets, high contrast, visible labels (no placeholder-only
  inputs), keyboard operable, status shown with text and icon, not color alone.
- Do not store uploads beyond request/job lifetime. Document this as an assumption.
- Commit in small steps with clear messages. Run tests before saying a step is done.

## Out of scope (document in README)

COLA integration, authentication, real PII handling and retention policy, FedRAMP concerns,
beverage-type-specific rules beyond the common fields.

## Definition of done for each task

1. Code written and runs.
2. Tests added or updated and passing.
3. Any new assumption or limitation recorded in `docs/DECISIONS.md`.
4. A short summary of what changed and what to verify manually.
