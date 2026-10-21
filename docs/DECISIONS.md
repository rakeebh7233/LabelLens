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
