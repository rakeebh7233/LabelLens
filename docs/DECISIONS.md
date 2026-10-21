# Decisions and Trade-offs

Each entry: what we chose, why, and what it costs.

## Scaffold

- **Single repo, FastAPI serves the built frontend.** One Docker image and one public URL. In
  development Vite runs separately on :5173 and proxies `/api` to :8000, so the frontend always
  calls same-origin `/api` and no CORS configuration is needed.
- **Backend venv in `backend/.venv`.** Isolates dependencies from the system Python. The Makefile
  handles the Windows (`Scripts/`) vs POSIX (`bin/`) layout.
- **Pinned `requirements.txt`, test tools included.** One file keeps setup to a single command.
  The cost is that pytest and httpx also install in the production image (small).
- **Settings from environment variables via a frozen dataclass** (`app/config.py`), prefixed
  `LABELLENS_`. Avoids adding pydantic-settings for a handful of values.
- **`/api/health` reports `tesseract_available`** so a missing system Tesseract shows up
  immediately rather than as confusing OCR errors later.
- **Known warning:** Starlette deprecates `httpx` in its test client in favour of `httpx2`. Tests
  still pass; revisit if it becomes an error.
- **GNU make is required for `make` targets.** It is not installed on Windows by default; the
  README lists the equivalent raw commands.

## Domain model

- **Three-state `Status` (pass / review / fail), never binary.** `review` is where judgment
  calls go (case-only differences, low OCR confidence, bold unverifiable) so the agent decides.
- **`overall_status` is computed, not stored.** It is a Pydantic computed field on
  `LabelResult` (worst field status via `worst_status`), so it can never disagree with the
  fields and still appears in JSON responses.
- **Nothing verified is never a pass.** An empty field list, or a label that could not be
  processed (`error` set, e.g. unreadable image), gives `fail`. A per-label `error` also lets
  one bad file in a batch become a result rather than failing the whole job.
- **`ApplicationData` keeps the raw strings the agent typed** (`"45% ABV (90 proof)"`,
  `"750 mL"`). Parsing lives in `matching/parsers.py` so it can be unit tested and so the
  original value can be quoted back in reasons. Blank required fields are rejected; unknown
  keys are ignored so CSV manifests with extra columns still load.
- **A review or fail result without a reason is a validation error.** This enforces the rule
  that every non-pass result explains itself in plain English.
- **The standard warning text lives in `schemas.py`** as `STANDARD_GOVERNMENT_WARNING`, the
  default for `ApplicationData.government_warning` and the reference for the warning check.
