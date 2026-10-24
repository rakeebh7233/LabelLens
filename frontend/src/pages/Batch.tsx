import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, cancelBatch, exportUrl, getBatch, startBatch } from "../api/client";
import type { BatchProgress, JobState, LabelResult } from "../api/types";
import BatchTable, { toRow, type BatchRow } from "../components/BatchTable";
import DetailPanel from "../components/DetailPanel";
import { isSupportedImage } from "../components/DropZone";
import FileDropArea from "../components/FileDropArea";
import { ManifestProblem, TEMPLATE_CSV, matchKey, pairPhotos, readManifest, type Manifest } from "../lib/manifest";

export const POLL_MS = 1500;
const LIST_LIMIT = 8;

const PRIMARY =
  "min-h-16 rounded-xl bg-blue-800 px-8 py-4 text-2xl font-bold text-white shadow hover:bg-blue-900 focus-visible:outline-4 focus-visible:outline-offset-4 focus-visible:outline-blue-700 disabled:cursor-not-allowed disabled:bg-slate-400";
const SECONDARY =
  "inline-flex min-h-12 items-center rounded-lg border-2 border-blue-800 bg-white px-6 py-2 text-lg font-semibold text-blue-900 hover:bg-blue-50 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-blue-700 disabled:opacity-50";

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

function NameList({ names }: { names: string[] }) {
  const shown = names.slice(0, LIST_LIMIT);
  return (
    <ul className="mt-1 list-disc pl-6 text-lg">
      {shown.map((name) => (
        <li key={name} className="break-all">
          {name}
        </li>
      ))}
      {names.length > shown.length && <li>and {names.length - shown.length} more</li>}
    </ul>
  );
}

function jobIdFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get("job");
}

function setJobInUrl(jobId: string | null) {
  const params = new URLSearchParams(window.location.search);
  params.set("view", "batch");
  if (jobId) params.set("job", jobId);
  else params.delete("job");
  window.history.pushState(null, "", `?${params}`);
}

interface JobView {
  state: JobState;
  progress: BatchProgress;
}

export default function Batch() {
  // Setup
  const [photos, setPhotos] = useState<File[]>([]);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [manifestFile, setManifestFile] = useState<File | null>(null);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [manifestError, setManifestError] = useState<string | null>(null);
  const [uploading, setUploading] = useState<number | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  // Running job
  const [jobId, setJobId] = useState<string | null>(jobIdFromUrl);
  const [job, setJob] = useState<JobView | null>(null);
  const [results, setResults] = useState<LabelResult[]>([]);
  const [pollProblem, setPollProblem] = useState<string | null>(null);
  const [notFound, setNotFound] = useState<string | null>(null);
  const [selected, setSelected] = useState<LabelResult | null>(null);

  const photoInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const manifestInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // Not in React's typings; lets the picker choose a whole folder.
    folderInput.current?.setAttribute("webkitdirectory", "");
  }, []);

  useEffect(() => {
    const onPop = () => setJobId(jobIdFromUrl());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // Poll the job, fetching only results not yet received, until it is done or cancelled.
  useEffect(() => {
    if (!jobId) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let since = 0;
    setResults([]);
    setJob(null);
    setNotFound(null);
    setPollProblem(null);

    async function poll() {
      try {
        const latest = await getBatch(jobId!, since);
        if (stopped) return;
        since += latest.results.length;
        if (latest.results.length) setResults((current) => [...current, ...latest.results]);
        setJob({ state: latest.state, progress: latest.progress });
        setPollProblem(null);
        if (latest.state === "done" || latest.state === "cancelled") return;
      } catch (error) {
        if (stopped) return;
        if (error instanceof ApiError && error.status === 404) {
          setNotFound(error.message);
          return;
        }
        setPollProblem("Lost contact with the server. Still trying...");
      }
      timer = setTimeout(poll, POLL_MS);
    }
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [jobId]);

  const brandByFile = useMemo(
    () => new Map((manifest?.rows ?? []).map((row) => [matchKey(row.filename), row.brand])),
    [manifest],
  );
  const rows: BatchRow[] = useMemo(
    () => results.map((result) => toRow(result, brandByFile.get(matchKey(result.filename ?? "")))),
    [results, brandByFile],
  );
  const pairing = useMemo(() => (manifest ? pairPhotos(photos, manifest) : null), [photos, manifest]);

  async function chooseManifest(file: File) {
    setManifestFile(file);
    setManifest(null);
    setManifestError(null);
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setManifestError(`${file.name} is not a CSV file. In Excel, use File > Save As and choose CSV.`);
      return;
    }
    try {
      setManifest(readManifest(await file.text()));
    } catch (error) {
      setManifestError(error instanceof ManifestProblem ? error.message : "The spreadsheet could not be read.");
    }
  }

  function addPhotos(files: File[]) {
    const images = files.filter(isSupportedImage);
    const others = files.filter((file) => !isSupportedImage(file));
    // A dropped folder often holds its spreadsheet too; use it if one has not been chosen.
    const csvs = others.filter((file) => file.name.toLowerCase().endsWith(".csv"));
    const foundManifest = csvs.length === 1 && !manifestFile ? csvs[0] : null;
    if (foundManifest) void chooseManifest(foundManifest);
    setPhotos(images);
    setSkipped(others.filter((file) => file !== foundManifest).map((file) => file.name));
    setStartError(null);
  }

  const startBlocked = !photos.length
    ? "To start, add the label photos."
    : !manifest
      ? "To start, add the spreadsheet (CSV file)."
      : pairing && !pairing.matched.length
        ? "None of the photos match a spreadsheet row. Check that the file names in the spreadsheet match the photos."
        : null;
  const mismatched = Boolean(pairing && (pairing.photosWithoutRow.length || pairing.rowsWithoutPhoto.length));

  async function start() {
    if (startBlocked || !pairing || !manifestFile) return;
    const csv = mismatched
      ? new File([pairing.matchedManifest], manifestFile.name, { type: "text/csv" })
      : manifestFile;
    setStartError(null);
    setUploading(0);
    try {
      const created = await startBatch(pairing.matched, csv, setUploading);
      setJobInUrl(created.job_id);
      setJobId(created.job_id);
    } catch (error) {
      setStartError(error instanceof Error ? error.message : "The batch could not be started.");
    } finally {
      setUploading(null);
    }
  }

  async function stop() {
    if (!jobId || !window.confirm("Stop checking? Labels already checked will be kept.")) return;
    try {
      const latest = await cancelBatch(jobId);
      setJob({ state: latest.state, progress: latest.progress });
    } catch (error) {
      setPollProblem(error instanceof Error ? error.message : "The batch could not be stopped.");
    }
  }

  function newBatch() {
    setJobInUrl(null);
    setJobId(null);
    setSelected(null);
    setPhotos([]);
    setSkipped([]);
    setManifestFile(null);
    setManifest(null);
    setManifestError(null);
  }

  const closePanel = useCallback(() => setSelected(null), []);

  if (jobId) {
    const progress = job?.progress;
    const finished = job?.state === "done" || job?.state === "cancelled";
    const percent = progress?.total ? Math.round((progress.completed / progress.total) * 100) : 0;
    return (
      <div className="space-y-6">
        {notFound ? (
          <div role="alert" className="rounded-xl border-4 border-red-700 bg-red-50 p-5 text-red-950">
            <h2 className="text-2xl font-bold">Batch not found</h2>
            <p className="mt-2 text-xl">{notFound}</p>
            <button type="button" onClick={newBatch} className={`${SECONDARY} mt-4`}>
              Start a new batch
            </button>
          </div>
        ) : (
          <>
            <section aria-labelledby="progress-heading" className="rounded-xl border-2 border-slate-300 bg-white p-5">
              <h2 id="progress-heading" className="text-2xl font-bold">
                {!job
                  ? "Loading the batch..."
                  : job.state === "cancelled"
                    ? "Checking stopped"
                    : finished
                      ? "Checking finished"
                      : "Checking labels..."}
              </h2>
              {progress && (
                <>
                  <p className="mt-2 text-xl" aria-live="polite">
                    {progress.completed} of {progress.total} checked
                    {finished &&
                      ` — ${plural(progress.failed, "fail", "fail")}, ${plural(progress.review, "needs review", "need review")}, ${plural(progress.passed, "pass", "pass")}`}
                  </p>
                  <div
                    role="progressbar"
                    aria-label="Labels checked"
                    aria-valuemin={0}
                    aria-valuemax={progress.total}
                    aria-valuenow={progress.completed}
                    aria-valuetext={`${progress.completed} of ${progress.total} checked`}
                    className="mt-3 h-6 overflow-hidden rounded-full bg-slate-200"
                  >
                    <div className="h-full bg-blue-800 transition-all" style={{ width: `${percent}%` }} />
                  </div>
                </>
              )}
              {pollProblem && (
                <p role="status" className="mt-3 text-lg font-medium text-amber-900">
                  {pollProblem}
                </p>
              )}
              <div className="mt-5 flex flex-wrap items-center gap-3">
                {finished ? (
                  <a href={exportUrl(jobId)} download className={SECONDARY}>
                    Download results (CSV)
                  </a>
                ) : (
                  <>
                    <button type="button" disabled aria-describedby="export-later" className={SECONDARY}>
                      Download results (CSV)
                    </button>
                    <span id="export-later" className="text-lg text-slate-700">
                      Available when checking finishes.
                    </span>
                  </>
                )}
                {job && !finished && (
                  <button
                    type="button"
                    onClick={stop}
                    className="inline-flex min-h-12 items-center rounded-lg border-2 border-red-800 bg-white px-6 py-2 text-lg font-semibold text-red-900 hover:bg-red-50 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
                  >
                    Stop checking
                  </button>
                )}
                {finished && (
                  <button type="button" onClick={newBatch} className={SECONDARY}>
                    Start a new batch
                  </button>
                )}
              </div>
            </section>

            <section aria-labelledby="results-heading">
              <h2 id="results-heading" className="mb-3 text-2xl font-bold">
                Results
              </h2>
              <BatchTable rows={rows} onOpen={(row) => setSelected(row.result)} selectedId={selected?.label_id} />
            </section>
          </>
        )}
        {selected && <DetailPanel result={selected} onClose={closePanel} />}
      </div>
    );
  }

  const busy = uploading !== null;
  return (
    <div className="space-y-8">
      <section aria-labelledby="step-photos">
        <h2 id="step-photos" className="text-2xl font-bold">
          1. Label photos
        </h2>
        <FileDropArea onFiles={addPhotos} disabled={busy}>
          <p className="text-xl">
            {photos.length ? `${plural(photos.length, "photo", "photos")} chosen` : "Drag label photos or a folder here"}
          </p>
          <div className="flex flex-wrap justify-center gap-3">
            <button type="button" onClick={() => photoInput.current?.click()} disabled={busy} className={SECONDARY}>
              Choose photos
            </button>
            <button type="button" onClick={() => folderInput.current?.click()} disabled={busy} className={SECONDARY}>
              Choose a folder
            </button>
          </div>
          <p className="text-base text-slate-700">JPEG, PNG, WebP or TIFF</p>
        </FileDropArea>
        {skipped.length > 0 && (
          <div className="mt-3 text-lg text-slate-800">
            <p>Skipped {plural(skipped.length, "file that is not a photo", "files that are not photos")}:</p>
            <NameList names={skipped} />
          </div>
        )}
        <input
          ref={photoInput}
          type="file"
          multiple
          accept=".jpg,.jpeg,.png,.webp,.tif,.tiff"
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          data-testid="photos-input"
          onChange={(event) => {
            addPhotos(Array.from(event.target.files ?? []));
            event.target.value = "";
          }}
        />
        <input
          ref={folderInput}
          type="file"
          multiple
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          onChange={(event) => {
            addPhotos(Array.from(event.target.files ?? []));
            event.target.value = "";
          }}
        />
      </section>

      <section aria-labelledby="step-manifest">
        <h2 id="step-manifest" className="text-2xl font-bold">
          2. Spreadsheet of application details
        </h2>
        <p className="mt-1 text-lg text-slate-700">
          One row per photo. The file name column must match each photo's file name.
        </p>
        <FileDropArea onFiles={(files) => files[0] && void chooseManifest(files[0])} disabled={busy}>
          <p className="text-xl">{manifestFile ? manifestFile.name : "Drag the CSV file here"}</p>
          <div className="flex flex-wrap justify-center gap-3">
            <button type="button" onClick={() => manifestInput.current?.click()} disabled={busy} className={SECONDARY}>
              {manifestFile ? "Choose a different CSV file" : "Choose a CSV file"}
            </button>
            <a
              href={`data:text/csv;charset=utf-8,${encodeURIComponent(TEMPLATE_CSV)}`}
              download="labellens-template.csv"
              className={SECONDARY}
            >
              Download CSV template
            </a>
          </div>
        </FileDropArea>
        {manifestError && (
          <p role="alert" className="mt-3 text-lg font-medium text-red-800">
            {manifestError}
          </p>
        )}
        <input
          ref={manifestInput}
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          data-testid="manifest-input"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void chooseManifest(file);
            event.target.value = "";
          }}
        />
      </section>

      <section aria-labelledby="step-start" className="space-y-4">
        <h2 id="step-start" className="text-2xl font-bold">
          3. Start checking
        </h2>
        {pairing && mismatched && (
          <div className="rounded-xl border-4 border-amber-600 bg-amber-50 p-5 text-amber-950">
            <p className="text-xl font-semibold">Some photos and rows do not match up.</p>
            {pairing.photosWithoutRow.length > 0 && (
              <div className="mt-3">
                <p className="text-lg">
                  {plural(pairing.photosWithoutRow.length, "photo has", "photos have")} no row in the spreadsheet:
                </p>
                <NameList names={pairing.photosWithoutRow} />
              </div>
            )}
            {pairing.rowsWithoutPhoto.length > 0 && (
              <div className="mt-3">
                <p className="text-lg">
                  {plural(pairing.rowsWithoutPhoto.length, "spreadsheet row has", "spreadsheet rows have")} no photo:
                </p>
                <NameList names={pairing.rowsWithoutPhoto} />
              </div>
            )}
            {pairing.matched.length > 0 && (
              <p className="mt-3 text-lg">You can fix the files and choose them again, or continue with the matches.</p>
            )}
          </div>
        )}
        <button
          type="button"
          onClick={start}
          disabled={Boolean(startBlocked) || busy}
          aria-describedby={startBlocked ? "start-blocked" : undefined}
          className={`${PRIMARY} w-full sm:w-auto`}
        >
          {pairing && mismatched
            ? `Continue with the ${plural(pairing.matched.length, "match", "matches")}`
            : `Start checking${pairing ? ` ${plural(pairing.matched.length, "label", "labels")}` : ""}`}
        </button>
        {startBlocked && (
          <p id="start-blocked" className="text-lg text-slate-800">
            {startBlocked}
          </p>
        )}
        {busy && (
          <p role="status" className="text-xl font-medium">
            Sending photos... {Math.round((uploading ?? 0) * 100)}%
          </p>
        )}
        {startError && (
          <div role="alert" className="rounded-xl border-4 border-red-700 bg-red-50 p-5 text-red-950">
            <p className="text-xl font-semibold">The batch could not be started</p>
            <p className="mt-1 text-lg">{startError}</p>
          </div>
        )}
      </section>
    </div>
  );
}
