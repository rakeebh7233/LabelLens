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
- **Bold:** bold -> pass; not bold or unknown -> review, never fail (see "Bold detection"
  below). `prefix_bold=None` now only means the caller had no image (text-only use) and
  passes with the note "bold type ... was not checked automatically".
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
- **Bold is checked on the image each OCR pass read** (see "Bold detection").

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
  - 14 prefix not bold: was a known gap until bold detection; **now review as expected**
    (Phase 12).
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

## Frontend: single label

- **No router or state library yet.** One page, local `useState`, and a typed `fetch` client
  (`src/api/`). `src/api/types.ts` mirrors `schemas.py` by hand; there are few enough types
  that generating them from OpenAPI is not worth the build step.
- **The disabled button explains itself.** "Check this label" stays disabled until a photo and
  the four required fields exist; a sentence under it names exactly what is missing and is
  wired to the button with `aria-describedby`. A disabled button cannot take focus, so the
  sentence is always visible rather than shown on hover.
- **The warning field is prefilled and collapsed.** Agents almost never change it; "Edit warning
  text" opens it, and "Reset to the standard text" appears once it differs.
- **Pass cards start closed, review and fail cards open**, so the agent's eye goes to what needs
  a decision. Each card is a button with `aria-expanded`; status is always icon plus word.
- **Focus moves to the outcome** (result banner or error heading) when a check finishes, so
  keyboard and screen-reader users land on it without hunting.
- **Three error states:** unreadable photo (the API returns 200 with `error` set), server error
  (the API's plain-language `detail` is shown as is), and network error. All offer "Try again".
- **Elapsed time is measured in the browser** (upload + OCR + response), which is what the agent
  actually waits for; the server's `timings_ms.total` is the fallback.
- **File type is checked in the browser too** (by extension, matching the server's list) so a
  wrong file is refused before upload. Size is left to the server, whose limit is configurable.
- **TIFF previews:** most browsers cannot display TIFF, so the drop zone says the photo cannot be
  previewed but can still be checked.
- **Not verified automatically:** layout at 1280px and 390px and a real screen-reader pass were
  checked by reading the markup, not with a browser; no headless browser in the dev environment.

## Frontend: batch

- **Cancel is a new route, `DELETE /api/batch/{id}`.** It marks the job `cancelled`; labels
  still waiting skip themselves (releasing their photo) when a worker reaches them, and a
  label already being read is discarded when it finishes. Results from before the stop are
  kept, and export is allowed for a cancelled job as well as a finished one: stopping is an
  explicit choice, so a partial file is not a surprise. The UI asks for confirmation first.
- **Mismatches are found in the browser before upload.** `src/lib/manifest.ts` reads the CSV
  (a small RFC 4180 parser; comma, semicolon or tab) with the same friendly column names as
  the server and pairs photos with rows by file name, ignoring folders and case. Photos
  without a row and rows without a photo are listed in plain language; "Continue with the N
  matches" uploads only the matched photos and a manifest rebuilt with only their rows. The
  server still re-checks everything and stays the authority. **The column aliases are
  duplicated** in `manifest.ts` and `services/manifest.py` and must be kept in step.
- **Missing required columns are caught before upload** too, so a wrong spreadsheet does not
  cost a few hundred MB of upload first.
- **Folders:** "Choose a folder" uses `webkitdirectory` (supported by all current browsers);
  dropped folders are walked with the File and Directory Entries API. Non-photo files are
  skipped and named. If a dropped folder holds exactly one CSV and no spreadsheet has been
  chosen yet, it is used as the spreadsheet (the sample folders are laid out this way).
- **Choosing photos again replaces the selection** rather than adding to it, so the count shown
  is always exactly what will be sent.
- **Upload uses XMLHttpRequest** because `fetch` cannot report upload progress, and a few
  hundred photos take long enough to need a "Sending photos... 45%" message.
- **Polling every 1.5 s with `since`**, so each poll carries only new results. A failed poll
  shows "Lost contact with the server. Still trying..." and keeps going; a 404 (expired or
  unknown job) stops and offers a new batch.
- **The job id lives in the URL** (`?view=batch&job=<id>`), so a refresh or the back button
  returns to the same batch while the server still holds it (60 minutes after finishing).
  Query string rather than paths because FastAPI serves `index.html` only at `/`. After a
  refresh the brand column falls back to what the results carry, since the spreadsheet is not
  re-read; error rows (which have no fields) then show no brand.
- **Table:** fails first, then review, then pass (more issues first within a status), with
  sortable column headers, filter chips with counts (`aria-pressed`) and a search over file
  name and brand. Rows are not virtualized; 300 rows render without trouble.
- **Detail panel is non-modal**, so the table stays usable while the batch runs. Focus moves
  to its Close button and returns to the row on close; Escape closes it. It is full screen
  on a phone.
- **Measured:** a 50-label batch with one corrupt file against the real backend finished in
  10 s on 4 workers, progress advancing every poll; the corrupt file became a row-level error
  and the other 49 completed. The browser layout itself was not checked in a real browser
  (no headless browser in the dev environment).

## Bold detection

- **Verdicts:** bold -> pass; not bold -> review ("does not look bold. It must be in bold
  type - check the label"); unknown -> review ("the photo is not clear enough to tell").
  Never fail: it is a heuristic, and Jenny's rejection of a non-bold prefix is the agent's
  call on seeing the label. The cost is that a label whose bold cannot be measured needs a
  look even when everything else matches.
- **Measurement:** mean stroke width per word = 2 x ink area / outline length (Otsu ink
  mask), divided by the word's box height; the verdict is the prefix's median over the body's
  median. **A distance transform was tried first and rejected**: its median ridge value
  moves in 0.4-0.6 px steps at warning-text sizes (strokes are 2-4 px), and on the samples
  it called sample 14's regular prefix bold (1.79) and the wine label's bold one regular
  (0.75). Area over outline measures below a pixel and separated them (1.13 and 1.52).
- **Normalized by cap height, not x-height** (a deliberate departure from the Phase 12
  prompt). The prefix is all capitals, so it has no x-height; dividing its cap height by
  the body's x-height would shrink it by about 1.4x, roughly the whole bold effect. Body
  words with tall letters and no descenders ("the", "birth", "defects") have box heights
  close to the cap height and serve as the reference.
- **Calibration** (OCR boxes from Tesseract; DejaVu Sans and Serif; all 23 samples, both OCR
  passes):
  - From 10 px cap height up, bold prefixes measured 1.38-1.88 and regular 0.96-1.19.
    Samples: bold 1.40-1.79, sample 14 (regular) 1.12-1.13.
  - At 9 px and below the ratio is noise (a regular prefix measured 1.42 at 9 px).
  - Thresholds: **bold at 1.30 or more, not bold at 1.22 or less**, unknown between, and
    **unknown below 12 px cap height**. Only the bold threshold changes an outcome (not
    bold and unknown are both review), so it sits well above every regular measurement.
- **Unknown instead of guessing** when: the text is under 12 px; the two prefix words differ
  in height by more than 1.3x, or the prefix and body heights do (OCR sometimes boxes two
  lines as one word: a merged box gave 0.36 at small sizes, and sample 19's heavy pass had
  prefix boxes 40 and 26 px tall); fewer than 3 reference body words; no prefix found.
- **Measured on the image each OCR pass read**, since the word boxes refer to it. Each
  reading now carries its image (`reader.Pass`). The retry decision ignores bold: retrying
  changes what OCR reads, but its black-and-white image is no better for stroke widths.
  As with other fields, the warning takes the better of the two passes' results.
- **Cost:** under 1 ms per label.
- **Sabotage check:** lowering the bold threshold to 1.05 fails 6 tests, including sample 14.
- **Limitations:**
  - Assumes the prefix and body are the same typeface at about the same size. A label that
    sets the prefix in a different, naturally heavier face could read as bold, and one
    that sets the whole warning in bold reads as not bold (review).
  - Synthetic labels only (DejaVu fonts, Pillow rendering). Real print, ink spread,
    embossing, metallic foil and JPEG artefacts are untested; expect more unknowns on real
    photos.
  - Text smaller than 12 px cap height in the processed image (about 1600 px long edge)
    is always unknown. A closer photo of the warning fixes it.
  - Light-on-dark text is handled by flipping the ink mask; coloured text on a busy
    background may threshold poorly and come back unknown.
- **Test helper change:** `tests/label_images.render_label` now prints the prefix in bold,
  as on a real label (`bold_prefix=False` for the regular version). Before, the whole
  warning was regular, which the detector correctly reported as not bold.
