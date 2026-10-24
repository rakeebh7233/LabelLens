import { useEffect, useRef } from "react";
import type { LabelResult } from "../api/types";
import LabelResultView from "./LabelResultView";

interface DetailPanelProps {
  result: LabelResult;
  onClose: () => void;
}

/**
 * Side panel with the same detail view as the single-label page. Not modal, so the table
 * stays usable while a batch runs. Escape or the close button closes it.
 */
export default function DetailPanel({ result, onClose }: DetailPanelProps) {
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // Remember where focus was (the row's file name) and return it on close.
    const returnTo = document.activeElement as HTMLElement | null;
    return () => returnTo?.focus();
  }, []);

  useEffect(() => {
    closeButton.current?.focus();
  }, [result.label_id]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside
      role="dialog"
      aria-labelledby="detail-title"
      className="fixed inset-0 z-20 overflow-y-auto border-l-4 border-slate-300 bg-slate-50 p-4 shadow-2xl sm:left-auto sm:w-[36rem] sm:p-6"
    >
      <div className="mb-4 flex items-start justify-between gap-4">
        <h2 id="detail-title" className="break-all text-2xl font-bold">
          {result.filename ?? "Label details"}
        </h2>
        <button
          ref={closeButton}
          type="button"
          onClick={onClose}
          className="min-h-12 shrink-0 rounded-lg border-2 border-slate-500 bg-white px-4 text-lg font-semibold hover:bg-slate-100 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
        >
          Close
        </button>
      </div>
      <LabelResultView result={result} />
    </aside>
  );
}
