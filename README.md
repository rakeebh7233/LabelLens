# LabelLens

AI-assisted label verification for alcohol compliance review. Upload a label image, enter the
application data, and LabelLens tells you field by field whether the label matches, in about
five seconds. It also handles batches of hundreds of labels.

**Live demo:** <TODO: deployed URL>
**Repository:** <TODO: GitHub URL>

<TODO: add 1-2 screenshots: single result with a "needs review" field, and the batch table>

> Prototype for evaluation. Standalone: no COLA integration, no authentication, no data
> retained after processing. See [Assumptions](#assumptions) and [Limitations](#known-limitations).

---

## Try it in 60 seconds

1. Open the live demo (or run locally, below).
2. Go to **Check one label**, drop in `samples/labels/01_old_tom_perfect.png`.
3. Click **Check this label**. Every field should come back green.
4. Now try `05_warning_titlecase.png` to see the warning rule fail, and `02_stones_throw_case.png`
   to see a "needs review" result.
5. Go to **Check many labels**, upload everything in `samples/labels/` plus
   `samples/applications.csv`.

## What it checks

| Field              | How it is compared                                                                        | Possible results     |
| ------------------ | ----------------------------------------------------------------------------------------- | -------------------- |
| Brand name         | Normalized text match, fuzzy fallback                                                     | Pass / Review / Fail |
| Class/type         | Normalized text match, fuzzy fallback                                                     | Pass / Review / Fail |
| Alcohol content    | Parsed numerically; ABV and proof are interchangeable                                     | Pass / Fail          |
| Net contents       | Parsed and converted to mL                                                                | Pass / Review / Fail |
| Government warning | Exact wording; "GOVERNMENT WARNING:" must be uppercase; bold check <TODO: if implemented> | Pass / Review / Fail |

**Three results, not two.** *Pass* means it matches. *Needs review* means it is probably fine but a
person should decide (for example `STONE'S THROW` vs `Stone's Throw`). *Fail* means a clear
mismatch. The overall label result is the worst field result. Every non-pass result includes a
plain-English reason.

---

## Quick start

### Option A: Docker (recommended)

```bash
docker compose up --build
# open http://localhost:8000
```

### Option B: Local development

Requirements: Python 3.11+, Node 20+, Tesseract OCR installed on the system.
Ubuntu 22.04 / WSL ships Python 3.10 and Node 12; `uv python install 3.12` and
`nvm install 20` get you current versions without sudo, and `make install` picks up
`python3.12` automatically.

```bash
# Tesseract
brew install tesseract              # macOS
sudo apt install tesseract-ocr      # Debian/Ubuntu

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload       # http://localhost:8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev                         # http://localhost:5173 (proxies /api to the backend)
```

### Tests and sample data

```bash
cd backend && pytest                # backend unit + API + sample tests
cd frontend && npm test             # component tests
python scripts/make_samples.py      # regenerate samples/labels and samples/applications.csv
```

---

## How it works

```
image -> resize/preprocess -> OCR (once) -> compare each field -> LabelResult
                                   |
                         timings_ms returned for every request
```

<TODO: replace with a small diagram or keep the ASCII flow>

1. **Preprocess** (OpenCV): cap image size, grayscale, boost contrast. If OCR confidence is low,
   also deskew and reduce glare.
2. **OCR once** (Tesseract, runs locally) and reuse the result for every field.
3. **Compare** each field with rules specific to that field (see table above).
4. **Report** a result per field with the expected value, the value found, and a reason.

Batches run through a bounded worker pool. Each label is isolated, so one unreadable file never
stops the batch. Results appear as they finish and can be exported as CSV.

## API

| Method | Path                               | Purpose                                                    |
| ------ | ---------------------------------- | ---------------------------------------------------------- |
| POST   | `/api/verify`                    | One image + application fields -> `LabelResult`          |
| POST   | `/api/batch`                     | Images + `manifest.csv` -> `{job_id}`                  |
| GET    | `/api/batch/{job_id}`            | Progress and results so far                                |
| GET    | `/api/batch/{job_id}/export.csv` | Download results                                           |
| GET    | `/api/health`                    | Health check (also reports whether Tesseract is available) |

Interactive docs: `/docs` (FastAPI Swagger UI).

**Batch manifest columns:** `filename, brand_name, class_type, alcohol_content, net_contents`
(optional: `government_warning`). Rows are matched to images by `filename`.

---

## How the stakeholder feedback shaped the design

| What we heard                                                                       | Decision                                                                                                                                                                    |
| ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| "If we can't get results in about 5 seconds, nobody's going to use it." (Sarah)     | Local OCR, one OCR pass per label, image downscaling, per-stage timings returned so the budget is measurable. <TODO: add your measured median/p95>                          |
| "Something my mother could figure out." (Sarah)                                     | One main action per page, large buttons, visible labels, plain-language messages, status shown with text and icons, not color alone.                                        |
| Batch uploads of 200-300 labels (Sarah)                                             | Batch page with CSV manifest, live progress, sortable table with fails first, CSV export.                                                                                   |
| Network blocks outbound domains; the previous vendor's ML endpoints failed (Marcus) | No cloud AI dependency. All OCR runs inside the app container.                                                                                                              |
| "You need judgment." STONE'S THROW vs Stone's Throw (Dave)                          | Three-state results. Case-only differences become *Needs review*, so the agent keeps the decision.                                                                        |
| Warning must be exact, uppercase and bold (Jenny)                                   | Word-for-word comparison against the canonical text; uppercase prefix enforced; <TODO: bold heuristic status>.                                                              |
| Bad angles, glare, poor lighting (Jenny)                                            | Conditional deskew and glare reduction when OCR confidence is low; very poor images produce *Needs review* with a hint to request a better photo instead of a false pass. |

## Tools and why

| Choice                  | Reason                                                   | Alternative considered                                                      |
| ----------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------- |
| Python + FastAPI        | Strongest OCR/image ecosystem; async-friendly uploads    | Node backend (weaker OCR tooling)                                           |
| Tesseract (local)       | No outbound calls, fast, easy to containerize            | Cloud vision APIs (blocked by firewall, added latency); PaddleOCR (heavier) |
| OpenCV                  | Standard for deskew/contrast/glare work                  | Pillow only (not enough)                                                    |
| rapidfuzz               | Fast fuzzy matching                                      | difflib (slower, fewer scorers)                                             |
| React + Vite + Tailwind | Fast to build accessible, clear UI                       | Server-rendered templates                                                   |
| Docker                  | Tesseract is a system dependency; one reproducible image | Native buildpack                                                            |

<TODO: link to docs/DECISIONS.md for the longer version>

---

## Assumptions

- Standalone prototype; no COLA integration or authentication.
- No sensitive data is stored. Uploads are processed in memory or temp storage and deleted after
  the request or batch job finishes. Batch jobs live in memory and expire after <TODO: TTL>.
- A production deployment would need document retention rules, PII handling, audit logging and
  federal compliance review. Out of scope here.
- Application data is entered by the user (single) or supplied in a CSV (batch).
- Warning text is compared against the standard statement in `backend/app/extract/warning.py`.
- Rules cover the common fields only. Beverage-specific rules (for example wine appellations or
  beer-specific exemptions) are not implemented.

## Known limitations

- **Bold detection** is a stroke-width heuristic and can return "unknown" on small or low-resolution
  text, which yields *Needs review* rather than a guess. <TODO: update to match what you built>
- OCR struggles with stylized or script fonts, heavily curved bottle text and non-English labels.
- Very low-quality photos may be flagged for a better image instead of being fully verified.
- Brand detection is verification-based (is the expected value on the label?). It does not
  discover the brand from scratch.
- Batch jobs are in memory and are lost on restart. <TODO: Render/Fly cold starts, instance size>
- Accessibility was tested with keyboard and basic screen reader checks only. <TODO: adjust>

## What I would do next

1. Persistent job queue and storage, with retention controls.
2. Authentication and an audit trail.
3. Side-by-side image viewer with highlighted regions where each field was found.
4. A trained text detector for hard photos, plus an optional vision-LLM fallback on an
   allowlisted endpoint.
5. Beverage-specific rule sets (beer, wine, spirits) and configurable thresholds per team.
6. Measure accuracy on a larger labeled set of real labels.

## Project layout

```
backend/    FastAPI app, OCR, matching rules, tests
frontend/   React + Vite UI
samples/    Test labels, batch manifest, expected outcomes
scripts/    Sample generator
docs/       DECISIONS.md
```

## Testing notes

<TODO: summarize coverage, e.g. "N unit tests for normalization/parsing/compare, M API tests,
sample-label regression test asserting expected status for each file">

**Measured performance** (<TODO: machine/instance>): single label median <TODO></todo> s, p95 <TODO></todo> s;
250-label batch in <TODO></todo> s.

## License / credits

<TODO: license, and note that all sample labels are synthetic with fictional brands>
