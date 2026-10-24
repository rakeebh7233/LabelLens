import { useId, useState } from "react";
import { FIELD_LABELS, type FieldResult } from "../api/types";
import StatusBadge, { STATUS_STYLES, StatusIcon } from "./StatusBadge";

/** One field's verdict. Review and fail cards start open; pass cards start closed. */
export default function ResultCard({ result }: { result: FieldResult }) {
  const [open, setOpen] = useState(result.status !== "pass");
  const detailsId = useId();
  const label = FIELD_LABELS[result.field];

  return (
    <li className={`rounded-xl border-2 bg-white ${result.status === "pass" ? "border-slate-300" : STATUS_STYLES[result.status].border}`}>
      <h3>
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls={detailsId}
          className="flex min-h-14 w-full flex-wrap items-center gap-3 rounded-xl px-4 py-3 text-left hover:bg-slate-50 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
        >
          <StatusIcon status={result.status} />
          <span className="text-xl font-semibold">{label}</span>
          <span className="ml-auto flex items-center gap-3">
            <StatusBadge status={result.status} />
            <svg
              className={`h-6 w-6 text-slate-600 transition-transform ${open ? "rotate-180" : ""}`}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2.5}
              aria-hidden="true"
            >
              <path d="m6 9 6 6 6-6" />
            </svg>
            <span className="sr-only">{open ? "Hide details" : "Show details"}</span>
          </span>
        </button>
      </h3>
      <div id={detailsId} hidden={!open} className="border-t-2 border-slate-200 px-4 pb-4 pt-3">
        {result.reason && <p className="text-lg font-medium">{result.reason}</p>}
        <dl className="mt-3 grid gap-4 md:grid-cols-2">
          <div className="rounded-lg bg-slate-100 p-3">
            <dt className="text-base font-semibold uppercase tracking-wide text-slate-700">Application says</dt>
            <dd className="mt-1 whitespace-pre-wrap break-words text-lg">{result.expected}</dd>
          </div>
          <div className="rounded-lg bg-slate-100 p-3">
            <dt className="text-base font-semibold uppercase tracking-wide text-slate-700">Label says</dt>
            <dd className="mt-1 whitespace-pre-wrap break-words text-lg">
              {result.found ?? <span className="italic text-slate-700">Not found on the label</span>}
            </dd>
          </div>
        </dl>
      </div>
    </li>
  );
}
