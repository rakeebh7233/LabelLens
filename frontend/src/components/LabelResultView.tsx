import type { Ref } from "react";
import type { LabelResult, Status } from "../api/types";
import ResultCard from "./ResultCard";
import { STATUS_STYLES, STATUS_TEXT, StatusIcon } from "./StatusBadge";

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

function summary(result: LabelResult): string {
  const count = (status: Status) => result.fields.filter((f) => f.status === status).length;
  if (result.error) {
    return `This label could not be checked. ${result.error}${/[.!?]$/.test(result.error) ? "" : "."}`;
  }
  if (result.overall_status === "pass") return "Every field matches the application.";
  if (result.overall_status === "review") {
    return `${plural(count("review"), "field")} need${count("review") === 1 ? "s" : ""} a closer look. You decide.`;
  }
  return `${plural(count("fail"), "field")} ${count("fail") === 1 ? "does" : "do"} not match the application.`;
}

interface LabelResultViewProps {
  result: LabelResult;
  // Round trip measured by the browser, including upload. Falls back to the server's total.
  elapsedMs?: number;
  // Lets the page move focus to the banner when a result arrives.
  headingRef?: Ref<HTMLHeadingElement>;
}

/** Overall banner, one card per field, and a quiet footer. Shared with the batch detail panel. */
export default function LabelResultView({ result, elapsedMs, headingRef }: LabelResultViewProps) {
  const status = result.overall_status;
  const elapsed = elapsedMs ?? result.timings_ms.total;
  const notes = [...result.warnings, ...result.preprocessing.map((step) => `Photo adjusted before reading: ${step}.`)];

  return (
    <section aria-labelledby={`result-${result.label_id}`}>
      <div className={`flex items-start gap-4 rounded-xl border-4 p-5 ${STATUS_STYLES[status].panel}`}>
        <StatusIcon status={status} className="h-12 w-12" />
        <div>
          <h2
            id={`result-${result.label_id}`}
            ref={headingRef}
            tabIndex={-1}
            className="text-3xl font-bold focus:outline-none"
          >
            {STATUS_TEXT[status]}
          </h2>
          <p className="mt-1 text-xl">{summary(result)}</p>
        </div>
      </div>

      <ul className="mt-5 space-y-3">
        {result.fields.map((field) => (
          <ResultCard key={field.field} result={field} />
        ))}
      </ul>

      <footer className="mt-5 space-y-1 text-base text-slate-700">
        {notes.map((note) => (
          <p key={note}>{note}</p>
        ))}
        {elapsed !== undefined && <p>Checked in {(elapsed / 1000).toFixed(1)} seconds.</p>}
      </footer>
    </section>
  );
}
