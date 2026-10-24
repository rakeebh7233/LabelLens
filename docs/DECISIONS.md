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

## Normalization and parsing

- **Normalization is a set of small steps, not one function.** `normalize_case` (unicode,
  case, whitespace) keeps punctuation, while `match_key` also strips punctuation and folds OCR
  look-alikes. Comparison can apply them in turn and name the difference ("differs only in
  capitalization" vs "only in punctuation"). Normalized text is only ever a matching key;
  reasons quote the original strings.
- **Apostrophes and periods are deleted; other punctuation becomes a space.** So
  "Stone's" == "Stones", "U.S.A." == "USA", "Single-Barrel" == "Single Barrel". Symbols such as
  (R) and TM are dropped. `&` is not treated as "and"; that difference falls through to fuzzy
  matching and lands in review.
- **OCR look-alikes (0->o, 1->l, |->l) are folded only inside tokens that contain letters.**
  "THR0W" matches "THROW", but "1792" stays a number. This misses a fully misread word made only
  of digits, which is rare and safer to leave as a visible difference.
- **ABV: a percentage next to an alcohol word wins over a bare percentage.** Without this,
  "100% Blue Agave ... 40% Alc/Vol" would read as 100%. If only a bare percentage exists it is
  used, and "ABV 45" (OCR dropped the %) is accepted as a last resort.
- **ABV and proof are parsed independently and not reconciled.** `45% (100 proof)` returns
  both numbers; deciding that they disagree is the comparison step's job. Values outside
  0-100% ABV or 0-200 proof are ignored as misreads. Proof is US proof (2 x ABV). "Proof 90"
  with the number after the word is not recognized.
- **Net contents use the first number followed by a volume unit,** so "Contents 750 mL
  (25.4 fl oz)" gives 750 mL and "12 x 355 mL" gives 355 mL. Plain "oz" is treated as fluid
  ounces (US fl oz, 29.5735 mL), and pint/quart/gallon are US measures. Combined forms like
  "1 PINT 9.4 FL OZ" read as 1 pint only.
- **A comma is a decimal mark unless exactly three digits follow it** ("40,5%" is 40.5,
  "1,000 mL" is 1000). "1,500 mL" is ambiguous in Europe; we read it as 1500.
- **A leading dash is a separator, not a minus sign** ("Bourbon -45%" is 45%). Zero and
  negative volumes are rejected.
- **Converted volumes are floats** (25.4 fl oz = 751.2 mL). The tolerance for "the same
  volume" belongs in comparison, not the parser.
- **Parsers return None on unusable input and never raise.** Covered by table tests plus a
  random-input fuzz run (50,000 strings) done during development.

## Comparison rules

- **Text fields check from strictest to loosest; the first check that holds decides.** Whitespace
  and curly vs straight quotes -> pass. Case only, punctuation only, or both -> review, with the
  reason naming which. Same after OCR look-alike folding -> review ("may be misread"). rapidfuzz
  ratio >= 90 on the matching keys -> review with the similarity. Anything else -> fail. Ordering
  this way gives the most specific reason available instead of a bare score.
- **Whitespace-only differences pass.** OCR breaks long brand names across lines, so treating
  "Old\nTom" as a difference would flood agents with noise.
- **Thresholds live in `MatchThresholds` (config.py)** and are set by environment variables:
  fuzzy review score (90), low OCR confidence (0.6), net contents tolerance (0.5%). ABV
  tolerance (0.05 points) only absorbs float rounding and is not exposed.
- **Low OCR confidence never causes a fail.** It turns pass into review, keeping any existing
  note (for example a unit conversion). *Revised in Phase 6:* it also turns a fail on text
  that *was found* into review ("may be a misreading"), because glare or blur can garble a
  correct label. A field that was not found at all, or a mismatch in clearly read text, still
  fails.
- **A label whose ABV and proof disagree fails; an application that disagrees with itself goes
  to review.** The label is what is being judged; a typo in the application is the agent's to
  sort out.
- **Unparseable values are review, missing values are fail.** If the field was found but no
  number could be read, the label may be fine and OCR at fault, so a person should look. If the
  field is absent, that is a clear problem.
- **Volumes within 0.5% are the same.** Needed because 25.4 fl oz (the usual US declaration
  for 750 mL) converts to 751.2 mL. 0.5% of 750 mL is about 3.75 mL, well below any real size
  difference (700 vs 750 mL is 6.7%). A unit conversion passes with an informational reason.
- **A pass may carry a reason** when it explains something useful (a proof-to-ABV or unit
  conversion). The UI should show it as a note, not a problem.
- **Thresholds are passed explicitly.** Comparison functions default to the built-in
  `MatchThresholds()`; the verify service (Phase 6) must pass `get_settings().thresholds` so
  environment overrides take effect.

## Government warning

- **Tolerant locating, strict judging.** `locate_warning` finds the block with a fuzzy
  alignment (`rapidfuzz.partial_ratio_alignment`), ignoring case and OCR noise, so the warning
  is found among other label text. `compare_warning` then judges word for word, case-sensitive.
  A score of 60 marks "found": real warnings score 80-100 and unrelated label text scores
  about 40. The match must also cover 30% of the warning, because very short text (for
  example "abc") gets a high partial score by chance.
- **The block is trimmed to solid runs of 3+ matching words.** Otherwise a common word such
  as "and" in the bottler line after a truncated warning would be counted as part of it. Edge
  words that resemble the expected words are kept, so a misread first or last word is judged,
  not dropped.
- **Line-end hyphens are joined before judging** ("preg-\nnancy" -> "pregnancy"). This is
  layout, not wording, and it is safe because the required text has no hyphenated words.
- **Prefix rules, checked first:** missing -> fail; not all capitals ("Government Warning:",
  "GOVERNMENT Warning:") -> fail; no colon -> fail. A colon OCR'd as a semicolon is a misread
  (review), not a missing colon.
- **OCR damage -> review, limited tightly.** It counts as damage only when every difference is
  a one-for-one word swap, each within 1 character edit (2 for words of 8+ letters), and at
  most 3 words differ. Anything else fails with a reason listing the differences (missing,
  extra, or "X where it should say Y"; the first 3, then "and N more"). The cost: a real
  one-letter change on a long word ("women" -> "woman") or a lost period lands in review rather
  than fail. A person still sees it, and nothing that differs ever passes.
- **Capitalization in the body is strict.** "surgeon general" fails. A case-only difference
  never counts as an OCR misread.
- **Bold (interim, until Phase 12).** `prefix_bold=None` (not checked) -> pass with the note
  "bold type ... was not checked automatically"; `False` -> review; `True` -> pass. Reporting
  every label as review until a detector exists would hide real problems behind noise. When
  Phase 12 lands, "unknown" becomes review.
- **One canonical text:** `STANDARD_GOVERNMENT_WARNING` in `schemas.py`. The check compares
  against `ApplicationData.government_warning`, which defaults to it.
- **`compare.py` helpers are public** (`make_result`, `downgrade_if_unsure`) so the warning
  check reuses the same result building and low-confidence rule.

## OCR and preprocessing

- **Two passes, the second only when needed.** `basic` (downscale to 1600px, grayscale,
  CLAHE) always runs, followed by one OCR call. `heavy` (lighting and glare flatten, deskew,
  adaptive threshold) runs only if the first reading is rejected; then the
  better-scoring reading wins. Measured locally on a synthetic label: clean 0.4 s,
  10-degree rotation about 1.0 s.
- **Mean confidence alone is a weak retry trigger.** Measured: a label rotated -7 degrees read
  at 0.91 confidence with the brand garbled ("ST ONE'S I HROWw"), and a shadowed label read at
  0.95 with half of each line missing. Tesseract is confident about what it read and silently
  drops what it could not. So `read_label` takes an `accept` check. The default is mean
  confidence >= 0.75 (`LABELLENS_OCR_RETRY_CONFIDENCE`); the verify service (Phase 6) will
  pass "every field matches on this reading", so the retry runs exactly when it could change
  the outcome.
- **Readings are compared by score, not mean confidence.** Score = sum of word length x
  confidence. Mean confidence would prefer a reading that found three easy words over one that
  found the whole label.
- **Tesseract tries psm 3 (automatic layout), then psm 11 (sparse text) if confidence is
  low,** keeping the higher score. *Revised in Phase 6:* the first version started with psm 6
  (one uniform block), which silently dropped large headline text. "OLD TOM DISTILLERY" at
  96px, wrapped over two lines, was missing from the reading while confidence stayed at
  0.96. Measured on five synthetic labels: psm 6 read the brand on 1 of 5, psm 3/4/11 on 5 of
  5, all at about 300 ms.
- **Deskew uses a projection-profile search** (coarse 1-degree steps over +/-15 degrees, then
  0.2-degree refinement, on an 800px copy, about 50 ms) instead of minAreaRect, which label
  borders and artwork throw off. Skew under 0.5 degrees is left alone. Larger rotations
  (sideways or upside-down photos) are not handled; phone EXIF orientation is applied on
  decode.
- **Glare is evened out, not inpainted.** The first version inpainted blown-out pixels
  (>= 250) before flattening. The rendered previews showed that the inpainted patch left a
  hard edge, which thresholding turned into black outlines through the text, so the heavy pass
  read glare labels worse than the basic one (score 180 vs 283). Dividing out the background
  already handles a hotspot's smooth brightness bump: without inpainting, the synthetic glare
  label scores 295 (the same as a clean label) and the warning is read in full. Glare is still
  detected (0.05%-25% of pixels >= 250) so the steps list says "glare evened out". Text that
  glare has fully washed out cannot be recovered by any preprocessing.
- **`ocr/reader.py` is an addition to the planned layout.** The retry loop needs both
  preprocessing and the engine, so it lives in neither; `preprocess.py` stays pure image
  functions and `engine.py` stays the swappable interface.
- **The Tesseract path is a pytesseract module-level setting.** It is set once from
  `LABELLENS_TESSERACT_CMD` when the engine is built. This is the one piece of
  library-owned global state.
- **Tests use Pillow-rendered labels** (DejaVu fonts, falling back to Pillow's built-in font)
  damaged by rotation, blur, glare and shadow. They are only a proxy for real photos. Tests
  that need Tesseract skip when it is not installed.

## Field extraction and the verify service

- **Search for the expected value instead of guessing the field.** Brand and class/type are
  found by scoring every run of consecutive OCR words (the expected length +/- 2 words, so OCR
  splits like "STONE' S" still match, and runs may cross line breaks) against the expected
  value with rapidfuzz. Under a score of 60 the value is treated as absent and a fallback
  runs: the tallest line in the top half for the brand, the first line with a beverage word
  for class/type. The fallback means a wrong label reads `Label says "HARBOR LIGHT"` instead of
  just "not found".
- **The government warning is excluded from the text search** (from "GOVERNMENT WARNING" for
  the length of the standard text), so a short class like "Wine" cannot match "women".
- **Numbers: every line is parsed and the one closest to the expected value wins.** For ABV,
  a separate proof-only line is joined on, so a label whose ABV and proof disagree is still
  caught. Choosing the closest value means a label that prints a second, different ABV
  somewhere else would not be flagged; that is unusual enough to accept.
- **A found value's confidence is its weakest word, not the mean.** On the glare sample,
  "Bourbon" at 0.92 beside a garbled word at 0.33 averaged to 0.79 and looked trustworthy.
- **The warning is judged with the whole reading's mean confidence,** since it spans many
  lines. A per-word measure would need the located block's words, not just its text.
- **Retry trigger: "every field passes on this reading".** `verify` passes this as the
  `accept` check to `read_label`, so a clean label costs one OCR pass. The retry runs exactly
  when a second, cleaner reading could change the outcome. A label with a real defect is
  always read twice (about 0.3-0.5 s extra), which is a fair price for not failing a good
  label because of a bad photo. Measured locally: perfect label 0.3-0.5 s; defects,
  rotation, glare and shadow 0.6-1.3 s.
- **Errors become results, never exceptions.** An unreadable file, an OCR failure, or any
  unexpected error returns a `LabelResult` with `error` set (overall fail) and a plain
  message. Unexpected errors are logged with the stack trace, which is never shown to the
  user.
- **No text found is not an error.** A blank image gives every field "not found" (fail) plus
  the hint "No text could be found on this image...". A reading under the low-confidence
  threshold adds "The photo was hard to read...".
- **`LabelResult` gained `preprocessing` (plain-language steps) and `ocr_confidence`,** so
  the UI can show what was done to the photo.
- **Bold is passed as "not checked" (`prefix_bold=None`)** until Phase 12.

## API and batch

- **Routes:** `POST /api/verify` (multipart photo + fields -> `LabelResult`), `POST /api/batch`
  (photos + CSV -> 202 `{job_id, total}`), `GET /api/batch/{id}?since=N`, `GET
  /api/batch/{id}/export.csv`, `GET /api/health`. Every error is `{"detail": "<plain
  sentence>"}`. Request validation errors and unexpected exceptions get generic plain
  messages; stack traces are only logged.
- **Single label:** a wrong file type (415), too large (413), empty (400), no photo (400) or
  blank fields (422, naming them) are rejected up front. An image that cannot be decoded
  returns 200 with a `LabelResult` whose `error` is set, the same shape a batch row uses, so
  the UI has one way to show it.
- **Batch: problems with single photos become error rows, never request failures.** A photo
  with no spreadsheet row, a row with no photo, a duplicate, a wrong file type, an oversized
  photo or a row with blank cells each become a `LabelResult` with a plain `error`. They show
  in the results table and the CSV export, so the agent sees every problem in one place. Only
  problems with the whole request are rejected: no spreadsheet, no photos, over 300 photos
  (`LABELLENS_MAX_BATCH_FILES`), photos totalling over 500 MB (`LABELLENS_MAX_BATCH_MB`), or a
  manifest that is not CSV, has missing columns or has no rows.
- **Manifest matching is forgiving:** by file name ignoring folders and letter case; friendly
  headers ("File Name", "Brand", "ABV", "Volume"); comma, semicolon or tab separated; UTF-8 or
  Excel's Windows-1252; a blank government warning means the standard text. Manifest parsing
  lives in `services/manifest.py`, an addition to the planned layout, because it is pure and
  tested on its own.
- **Threads, not processes, for the worker pool.** Tesseract runs as a child process and
  OpenCV releases the GIL, so threads parallelize the heavy work without pickling images.
  Measured with 20 labels: 1 worker 11.1 s, 4 workers 3.4 s.
- **`OMP_THREAD_LIMIT=1`** (set in the Dockerfile and by the engine if unset). Each Tesseract
  otherwise starts its own threads and parallel workers oversubscribe the CPU: 8 workers took
  3.9 s for 20 labels without it and 2.2 s with it. The default stays `min(4, cpu count)`
  workers. On a 1-vCPU host expect about 0.5 s per label, so 300 labels take about 2.5
  minutes.
- **Polling, not streaming.** `GET /api/batch/{id}?since=N` returns progress plus only the
  results after the first N, so the table fills in without resending everything each poll.
  Simpler to build and to run behind proxies than server-sent events or websockets.
- **In-memory job store with a TTL.** Jobs live in `JobStore` (one lock; the only shared
  mutable state) and are dropped 60 minutes after finishing (`LABELLENS_BATCH_TTL_MINUTES`).
  This is done lazily on each access, with no background thread. A restart forgets every job.
  This only works on a single server process: running several uvicorn workers would split
  jobs between them.
- **Uploads are never written by the app.** Photos are read into memory, and each one's bytes
  are released as soon as it has been checked. Starlette may spool a large upload to a
  temporary file while the request is being received; that file is deleted when the request
  ends. The 500 MB batch cap exists because photos wait in memory until checked.
- **Export waits for the batch to finish (409 while running)** so a partial file is never
  mistaken for the full result. Rows are fails first, then review, then pass. Cells starting
  with `= + - @` are prefixed with `'` so spreadsheet apps do not run OCR text as a formula.

## Sample labels and the regression suite

- **One generator, everything derived.** `scripts/make_samples.py` renders the 23 labels
  from `samples_lib/spec.py`, plus `applications.csv`, `applications_with_orphans.csv`,
  `expected.json`, the edge cases, a contact sheet and `samples/README.md`. Fixed seeds and
  bundled fonts make it deterministic (two runs gave 33 identical files). `huge.png` (over
  10 MB) and `samples/load/` (250 labels) are generated but gitignored.
- **Fictional names only.** The spec's "Harbor Light" and "Cedar Ridge" belong to real
  companies, so they became Harbor Wren, Bramblewick and Quillmoor.
- **DejaVu fonts only** (Bitstream Vera licence, bundled with its licence text). The Ubuntu
  fonts on the dev machine were left out because their licence carries trademark terms that
  Debian treats as non-free.
- **Shared damage functions.** The rotate/blur/glare/shadow helpers moved from
  `backend/tests/label_images.py` into `scripts/samples_lib/defects.py`, unchanged; the tests
  import them through `pythonpath = . ../scripts` in pytest.ini. The OCR previews
  (`samples/ocr_synthetic/`) were deleted in favour of the full sample set.
- **Smooth paper texture.** Per-pixel grain made every PNG about 2.8 MB (noise does not
  compress); low-frequency mottling keeps backgrounds uneven at about 600 KB per label.
- **Expected results can be loose for degraded photos:** `not_fail` (pass or review) for a
  good label photographed badly, `not_pass` (review or fail) when glare hides a field.
- **Samples that do not produce the spec's expected result are strict expected failures**
  (`KNOWN_GAPS` in `samples_lib/spec.py`, also listed in the samples README). Three came up;
  decisions:
  - 04 "OLD T0M" (zero): **expect pass, accepted limitation.** Tesseract reads the zero as
    the letter O at 0.94 confidence, so no matching rule can see it; a person reading the
    label would struggle too.
  - 14 prefix not bold: **kept as a known gap** until bold detection (Phase 12, optional)
    exists. The result says bold was not checked automatically.
  - 15 tiny warning text: **expect fail, accepted as conservative.** OCR reads none of the
    11 px warning, which is indistinguishable from an absent warning. Upscaling in the second
    pass might rescue it, but it was not adopted.
- **Pipeline fixes found by the samples:**
  - Net contents accepts "0Z" for "OZ", a common OCR misread (beer label).
  - *Each field takes its best result across both OCR readings* (`best_per_field`). On the
    perspective sample, the first reading got the brand and volume right while the second
    got the class/type and warning; keeping one whole reading lost fields that were plainly
    on the label. Ties keep the higher-scoring reading. A field matched in either reading
    of the same photo is on the label, so this does not create false passes.
  - *The warning is judged on its own words' confidence* (20th percentile of the block's
    words) instead of the whole label's mean. On curved text the warning was half garbled
    while the brand was crisp, and the mean (0.74) made a misreading look like a misprint.
    The percentile is low only when at least a fifth of the warning's words are; one smudged
    word does not soften a real rewording.
- **Sabotage check:** making brand capitalization differences pass makes sample 02 fail, as
  intended. Disabling only the capitals check on the warning prefix fails no sample, because
  the word-for-word check is also case-strict and still rejects "Government Warning:". The
  two rules back each other up.
- **Measured:** median 958 ms per sample label (max 1.1 s). 250 labels in 44 s with 4
  workers (0.18 s per label).
