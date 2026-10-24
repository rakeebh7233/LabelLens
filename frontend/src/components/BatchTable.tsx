import { useMemo, useState } from "react";
import type { LabelResult, Status } from "../api/types";
import StatusBadge from "./StatusBadge";

export type Filter = "all" | Status;
type SortKey = "status" | "filename" | "brand" | "issues";

const SEVERITY: Record<Status, number> = { fail: 0, review: 1, pass: 2 };
const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "fail", label: "Fail" },
  { key: "review", label: "Needs review" },
  { key: "pass", label: "Pass" },
];
const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "filename", label: "File" },
  { key: "brand", label: "Brand" },
  { key: "status", label: "Result" },
  { key: "issues", label: "Issues" },
];

export interface BatchRow {
  result: LabelResult;
  brand: string;
  // Fields that are not a pass. Rows that could not be checked count as one issue.
  issues: number;
}

export function toRow(result: LabelResult, brandFallback = ""): BatchRow {
  const brand = result.fields.find((f) => f.field === "brand_name")?.expected ?? brandFallback;
  const issues = result.error ? 1 : result.fields.filter((f) => f.status !== "pass").length;
  return { result, brand, issues };
}

function compare(a: BatchRow, b: BatchRow, key: SortKey): number {
  const byName = (a.result.filename ?? "").localeCompare(b.result.filename ?? "", undefined, { numeric: true });
  switch (key) {
    case "status":
      return SEVERITY[a.result.overall_status] - SEVERITY[b.result.overall_status] || b.issues - a.issues || byName;
    case "issues":
      return a.issues - b.issues || byName;
    case "brand":
      return a.brand.localeCompare(b.brand) || byName;
    default:
      return byName;
  }
}

/** Sort, filter and search; fails first by default. */
export function visibleRows(rows: BatchRow[], filter: Filter, search: string, key: SortKey = "status", ascending = true) {
  const needle = search.trim().toLowerCase();
  return rows
    .filter((row) => filter === "all" || row.result.overall_status === filter)
    .filter(
      (row) =>
        !needle || (row.result.filename ?? "").toLowerCase().includes(needle) || row.brand.toLowerCase().includes(needle),
    )
    .sort((a, b) => (ascending ? 1 : -1) * compare(a, b, key));
}

function issuesText(row: BatchRow): string {
  if (row.result.error) return `Could not check: ${row.result.error}`;
  if (row.issues === 0) return "None";
  return `${row.issues} ${row.issues === 1 ? "issue" : "issues"}`;
}

interface BatchTableProps {
  rows: BatchRow[];
  onOpen: (row: BatchRow) => void;
  selectedId?: string | null;
}

export default function BatchTable({ rows, onOpen, selectedId }: BatchTableProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; ascending: boolean }>({ key: "status", ascending: true });

  const shown = useMemo(() => visibleRows(rows, filter, search, sort.key, sort.ascending), [rows, filter, search, sort]);
  const counts = useMemo(() => {
    const result: Record<Filter, number> = { all: rows.length, fail: 0, review: 0, pass: 0 };
    for (const row of rows) result[row.result.overall_status]++;
    return result;
  }, [rows]);

  function sortBy(key: SortKey) {
    setSort((current) => ({ key, ascending: current.key === key ? !current.ascending : true }));
  }

  return (
    <div>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div role="group" aria-label="Show" className="flex flex-wrap gap-2">
          {FILTERS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              aria-pressed={filter === key}
              onClick={() => setFilter(key)}
              className={`min-h-12 rounded-full border-2 px-5 text-lg font-semibold focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-blue-700 ${
                filter === key ? "border-blue-800 bg-blue-800 text-white" : "border-slate-400 bg-white text-slate-900 hover:bg-slate-50"
              }`}
            >
              {label} ({counts[key]})
            </button>
          ))}
        </div>
        <div>
          <label htmlFor="batch-search" className="block text-lg font-semibold">
            Search by file name or brand
          </label>
          <input
            id="batch-search"
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="mt-1 block min-h-12 w-full rounded-lg border-2 border-slate-500 bg-white px-3 text-lg focus-visible:border-blue-700 focus-visible:outline-4 focus-visible:outline-offset-1 focus-visible:outline-blue-700/40 lg:w-80"
          />
        </div>
      </div>

      <div className="mt-4 overflow-x-auto rounded-xl border-2 border-slate-300 bg-white">
        <table className="w-full min-w-[36rem] text-left text-lg">
          <caption className="sr-only">Batch results. Choose a file name to see its details.</caption>
          <thead className="border-b-2 border-slate-300 bg-slate-100">
            <tr>
              {COLUMNS.map(({ key, label }) => (
                <th
                  key={key}
                  scope="col"
                  aria-sort={sort.key === key ? (sort.ascending ? "ascending" : "descending") : "none"}
                  className="p-0"
                >
                  <button
                    type="button"
                    onClick={() => sortBy(key)}
                    className="flex min-h-12 w-full items-center gap-1 px-4 font-semibold hover:bg-slate-200 focus-visible:outline-4 focus-visible:-outline-offset-4 focus-visible:outline-blue-700"
                  >
                    {label}
                    <span aria-hidden="true" className="text-slate-600">
                      {sort.key === key ? (sort.ascending ? "▲" : "▼") : ""}
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr
                key={row.result.label_id}
                onClick={() => onOpen(row)}
                className={`cursor-pointer border-b border-slate-200 last:border-0 hover:bg-blue-50 ${
                  selectedId === row.result.label_id ? "bg-blue-50" : ""
                }`}
              >
                <td className="px-4 py-3">
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      onOpen(row);
                    }}
                    className="break-all text-left font-medium text-blue-900 underline underline-offset-2 focus-visible:outline-4 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
                  >
                    {row.result.filename ?? "(no file name)"}
                  </button>
                </td>
                <td className="px-4 py-3">{row.brand}</td>
                <td className="px-4 py-3">
                  <StatusBadge status={row.result.overall_status} />
                </td>
                <td className="px-4 py-3">{issuesText(row)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!shown.length && (
          <p className="p-6 text-lg text-slate-700">
            {rows.length ? "No labels match this filter or search." : "Results will appear here as labels are checked."}
          </p>
        )}
      </div>
    </div>
  );
}
