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
- **Low OCR confidence only ever downgrades pass to review,** keeping any existing note (for
  example a unit conversion). It never turns anything into fail and never upgrades a fail.
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
