import { useEffect, useRef, useState } from "react";
import { ApiError, verifyLabel } from "../api/client";
import type { ApplicationFields, LabelResult } from "../api/types";
import DropZone from "../components/DropZone";
import FieldForm, { EMPTY_FIELDS, missingFields } from "../components/FieldForm";
import LabelResultView from "../components/LabelResultView";

type CheckState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "done"; result: LabelResult; elapsedMs: number }
  // "unreadable": the server answered but could not read the photo.
  | { kind: "error"; title: string; message: string; unreadable: boolean };

function joinWords(words: string[]): string {
  if (words.length <= 1) return words.join("");
  return `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`;
}

/** Why the check button is disabled, or null when it can be pressed. */
export function blockedReason(file: File | null, fields: ApplicationFields): string | null {
  const missing = [...(file ? [] : ["a label photo"]), ...missingFields(fields).map((name) => `the ${name}`)];
  return missing.length ? `To check this label, add ${joinWords(missing)}.` : null;
}

export default function Verify() {
  const [file, setFile] = useState<File | null>(null);
  const [fields, setFields] = useState<ApplicationFields>(EMPTY_FIELDS);
  const [state, setState] = useState<CheckState>({ kind: "idle" });
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const errorHeading = useRef<HTMLHeadingElement>(null);
  const abort = useRef<AbortController | null>(null);

  const loading = state.kind === "loading";
  const blocked = blockedReason(file, fields);

  // Move focus to the outcome so keyboard and screen-reader users land on it.
  useEffect(() => {
    if (state.kind === "done") resultHeading.current?.focus();
    if (state.kind === "error") errorHeading.current?.focus();
  }, [state.kind]);

  useEffect(() => () => abort.current?.abort(), []);

  async function check() {
    if (!file || blocked) return;
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setState({ kind: "loading" });
    const started = performance.now();
    try {
      const result = await verifyLabel(file, fields, controller.signal);
      if (result.error) {
        setState({ kind: "error", title: "We could not read this photo", message: result.error, unreadable: true });
      } else {
        setState({ kind: "done", result, elapsedMs: performance.now() - started });
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      const network = error instanceof ApiError && error.kind === "network";
      setState({
        kind: "error",
        title: network ? "Could not reach the server" : "The label could not be checked",
        message: error instanceof Error ? error.message : "Something went wrong. Please try again.",
        unreadable: false,
      });
    }
  }

  function startOver() {
    abort.current?.abort();
    setFile(null);
    setFields(EMPTY_FIELDS);
    setState({ kind: "idle" });
    window.scrollTo({ top: 0 });
  }

  return (
    <div className="space-y-8">
      <div className="grid gap-8 md:grid-cols-2">
        <DropZone file={file} onFileChange={setFile} disabled={loading} />
        <FieldForm fields={fields} onChange={setFields} disabled={loading} />
      </div>

      <div className="flex flex-col items-start gap-3">
        <button
          type="button"
          onClick={check}
          disabled={Boolean(blocked) || loading}
          aria-describedby={blocked ? "check-blocked" : undefined}
          className="min-h-16 w-full rounded-xl bg-blue-800 px-8 py-4 text-2xl font-bold text-white shadow hover:bg-blue-900 focus-visible:outline-4 focus-visible:outline-offset-4 focus-visible:outline-blue-700 disabled:cursor-not-allowed disabled:bg-slate-400 sm:w-auto"
        >
          Check this label
        </button>
        {blocked && (
          <p id="check-blocked" className="text-lg text-slate-800">
            {blocked}
          </p>
        )}
      </div>

      <div aria-live="polite">
        {loading && (
          <div className="flex items-center gap-4 rounded-xl border-2 border-slate-300 bg-white p-5" role="status">
            <span
              className="h-10 w-10 animate-spin rounded-full border-4 border-slate-300 border-t-blue-800"
              aria-hidden="true"
            />
            <p className="text-xl font-medium">Reading the label...</p>
          </div>
        )}
      </div>

      {state.kind === "error" && (
        <div role="alert" className="rounded-xl border-4 border-red-700 bg-red-50 p-5 text-red-950">
          <h2 ref={errorHeading} tabIndex={-1} className="text-2xl font-bold focus:outline-none">
            {state.title}
          </h2>
          <p className="mt-2 text-xl">{state.message}</p>
          {state.unreadable && (
            <p className="mt-2 text-lg">
              A sharper, well-lit photo taken straight on usually helps. You can choose a different file above.
            </p>
          )}
          <button
            type="button"
            onClick={check}
            disabled={Boolean(blocked)}
            className="mt-4 min-h-12 rounded-lg border-2 border-red-800 bg-white px-6 py-2 text-lg font-semibold text-red-900 hover:bg-red-100 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
          >
            Try again
          </button>
        </div>
      )}

      {state.kind === "done" && (
        <div className="space-y-5">
          <LabelResultView result={state.result} elapsedMs={state.elapsedMs} headingRef={resultHeading} />
          <button
            type="button"
            onClick={startOver}
            className="min-h-12 rounded-lg border-2 border-blue-800 bg-white px-6 py-2 text-lg font-semibold text-blue-900 hover:bg-blue-50 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
          >
            Check another label
          </button>
        </div>
      )}
    </div>
  );
}
