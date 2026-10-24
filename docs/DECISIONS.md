# Decisions and Trade-offs

The decisions that shape how LabelLens behaves: what was chosen, why, and what it costs.

## 1. Local OCR, no cloud AI

**Chosen:** Tesseract running inside the app, behind a small `OcrEngine` interface.
**Why:** The agency firewall blocks many outbound domains (Marcus), and label data should not
leave the network. A local engine also has predictable speed and cost.
**Cost:** Tesseract is weaker than a vision model on stylized fonts, curved bottles and poor
photos. The interface lets RapidOCR or PaddleOCR be swapped in; an LLM fallback stays off.

## 2. Three results, never two

**Chosen:** every field is *pass*, *needs review* or *fail*; the label gets the worst of its
fields. Every non-pass result carries a plain-English reason (enforced by the data model).
**Why:** Agents need judgment calls surfaced, not hidden (Dave: "STONE'S THROW" vs "Stone's
Throw" is the same brand). Review is where the tool says "probably fine, you decide".
**Rules that follow from it:**
- **Uncertainty never fails.** Low OCR confidence turns a pass, or a mismatch in text that
  was found, into review. Only a field that is clearly wrong or absent fails.
- **Nothing checked is never a pass.** An unreadable image or a label with no fields is a fail.
**Cost:** More reviews than a binary tool would give, especially on poor photos.

## 3. Find the expected value; compare from strictest to loosest

**Chosen:** the tool searches the label for what the application says (fuzzy-matching runs of
OCR words), rather than trying to work out which text is the brand. Comparison then tries the
strictest test first and stops at the first that holds:
- Identical apart from whitespace or curly quotes -> pass.
- Differs only in capitals and/or punctuation -> review, saying which.
- Same once common OCR misreads are folded (0/O, 1/l) -> review.
- Fuzzy similarity 90+ -> review. Anything else -> fail.

**Why:** Verification is an easier problem than discovery, and the ladder gives the most
specific reason available ("differs only in capitalization") instead of a bare score.
**Cost:** The tool cannot report what a label says if it is nothing like the application; a
fallback (largest line for brand, first beverage word for class) gives a best guess.

## 4. Numbers are parsed, not string-matched

**Chosen:** alcohol content and net contents are parsed to numbers. 45% equals 90 proof; 750 mL
equals 75 cL and 25.4 fl oz (volumes within 0.5% are the same, because the standard US fl oz
declaration converts to 751.2 mL). A label whose own ABV and proof disagree fails.
**Why:** These are the fields where formatting varies most and the meaning doesn't.
**Cost:** Unusual forms ("1 PINT 9.4 FL OZ", "Proof 90" with the number after) are not read;
a found-but-unparseable value goes to review rather than fail.

## 5. Government warning: find it tolerantly, judge it strictly

**Chosen:** the warning block is located with fuzzy matching (ignores case and OCR noise), then
judged word for word, case-sensitive. "GOVERNMENT WARNING:" must be all capitals with its colon;
title case fails (Jenny).
**OCR damage vs real change:** a difference counts as a possible misread (review) only when
every difference is a one-for-one word swap within one or two letters, at most three words.
Anything else fails, listing the differences.
**Cost:** A real one-letter change ("women" -> "woman") lands in review rather than fail. It
is still flagged; nothing that differs ever passes.

## 6. Bold prefix: a measured heuristic that can say "unknown"

**Chosen:** stroke width per word (2 x ink area / outline length, divided by the word's
height), prefix compared with the warning body. Bold (ratio 1.30+) passes; not bold (1.22 or
less) or unknown is review, never fail.
**Why this measure:** a distance-transform estimate was tried first and got the samples
backwards; at warning-text sizes (2-4 px strokes) its steps are as large as the bold effect.
**Normalized by cap height, not x-height:** the all-caps prefix has no x-height; dividing its
cap height by the body's x-height would cancel most of the bold signal.
**Unknown instead of guessing** below 12 px cap height (where a regular prefix measured as
bold), when OCR word boxes don't fit the text, or with too few body words.
**Calibration:** from 10 px up, bold measured 1.38-1.88 and regular 0.96-1.19 (DejaVu Sans and
Serif, plus every sample). Only the bold threshold changes an outcome, and it sits well above
every regular measurement.
**Cost:** Calibrated on synthetic labels only; real print, foil and JPEG photos will give more
"unknown" (review). Assumes the prefix and body share a typeface and size.

## 7. OCR pipeline: cheap first, retry only when it could matter

**Chosen:** one light pass (resize to 1600 px, grayscale, contrast). A heavier pass (lighting
flatten, deskew, black-and-white) runs only if some field does not pass on the first reading.
Each field then takes the better result from the two readings.
**Why:** A clean label costs one OCR call (about 0.4 s), keeping the 5-second budget. OCR
confidence alone was a poor retry trigger: Tesseract was 0.91-0.95 confident on readings that
had garbled or silently dropped half the text. Different cleanups often read different fields
well, so keeping one whole reading lost fields that were plainly on the label.
**Notable findings:**
- Tesseract's "uniform block" mode dropped large brand text; automatic layout (psm 3) with a
  sparse-text retry (psm 11) read it on every test label.
- Inpainting glare drew hard edges through text; dividing out the background works better.

**Cost:** A label with a real defect is always read twice (about 0.3-0.5 s extra).
Sideways or upside-down photos are not handled.

## 8. Batch: one bad file never stops the rest

**Chosen:**
- **Per-photo problems become rows, not request errors.** No spreadsheet row, no photo,
  duplicates, wrong type, unreadable image: each appears in the table and CSV with a plain
  reason. Only whole-request problems (no CSV, missing columns, too many photos) are rejected.
- **Mismatches are caught in the browser before upload,** with the option to continue with
  only the photos that match a spreadsheet row.
- **Threads, not processes,** with Tesseract limited to one thread each: Tesseract runs as a
  separate process anyway, and without the limit parallel workers oversubscribe the CPU
  (20 labels: 3.9 s -> 2.2 s with the limit). Worker count follows the container's CPU quota.
- **Polling, not streaming:** the browser asks every 1.5 s for results it has not seen yet.
  Simpler than websockets and works behind any proxy.
- **Jobs live in memory** with a 60-minute expiry after finishing, and can be cancelled
  (finished results are kept). The job id is in the URL, so a refresh resumes.

**Cost:** The app must run as a single process on a single instance; a restart or a sleeping
host forgets running batches.

## 9. Nothing is stored

**Chosen:** uploads are read into memory and each photo's bytes are released as soon as it is
checked. Nothing is written to disk by the app; batch results expire.
**Why:** No sensitive data stored (Marcus). Out of scope: retention policy, PII handling, audit.
**Cost:** Photos wait in memory until checked, so batch size is capped by total megabytes.

## 10. Interface built for the least technical user

**Chosen:** large text and targets, visible labels, status as icon plus word (never colour
alone), one obvious primary button that says why it is disabled, review and fail details open
by default, plain-language errors with a retry, focus moved to the result for keyboard and
screen-reader users.
**Why:** Sarah's test: usable by a 73-year-old without hunting for buttons.
**Cost:** Checked with automated component tests and by reading the markup; not yet tried with
a real screen reader or real agents.

## 11. Synthetic, reproducible test labels

**Chosen:** a script renders 23 labels (good labels, each defect, three layouts, photo damage)
with fixed seeds and bundled open-licence fonts; a regression test checks every sample's
expected result. Brand names are fictional.
**Accepted limitations found by the samples:**
- "OLD T0M" (zero for O) passes: Tesseract reads the zero as O at 0.94 confidence.
- An 11 px warning fails as absent: OCR reads none of it.

**Cost:** Synthetic labels are only a proxy for real photos. Accuracy on real labels is
unmeasured and is the most important next step.

## 12. Deployment: Render's free tier, measured honestly

**Chosen:** one Docker image (frontend built in, served by FastAPI) deployed with
`render.yaml` to Render's free tier, under a no-cost constraint. Hugging Face Docker Spaces
now require a paid plan; Fly.io, Railway and Cloud Run need a card or are trials; Oracle's
free VM means running a server by hand.
**Measured** with the container's CPU capped (all 23 samples, results identical every time):

| CPU | Median per label |
| --- | --- |
| 1 | 0.77 s |
| 0.5 | 1.47 s |
| 0.1 | 7.60 s |

About 0.75 CPU-seconds per label: half a CPU meets the 5-second target comfortably.
**Accuracy over speed:** shrinking images to 1200 px to help the free tier only reached 6.2 s
and wrongly failed a sample, so it was rejected.
**Cost:** The free tier sleeps after 15 idle minutes (about a minute to wake) and probably
misses the 5-second target. An agency deployment would run the same image on its own network.
