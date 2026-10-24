import { useEffect, useState } from "react";
import Batch from "./pages/Batch";
import Verify from "./pages/Verify";

type View = "verify" | "batch";

// The view lives in the query string (?view=batch&job=...) so a refresh or a shared link
// returns to the same place; FastAPI only serves index.html at "/", so no path routing.
function viewFromUrl(): View {
  return new URLSearchParams(window.location.search).get("view") === "batch" ? "batch" : "verify";
}

const TABS: { view: View; label: string }[] = [
  { view: "verify", label: "Check one label" },
  { view: "batch", label: "Check many labels" },
];

export default function App() {
  const [view, setView] = useState<View>(viewFromUrl);

  useEffect(() => {
    const onPop = () => setView(viewFromUrl());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  function go(next: View) {
    if (next === view) return;
    window.history.pushState(null, "", next === "batch" ? "?view=batch" : window.location.pathname);
    setView(next);
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b-2 border-slate-200 bg-white">
        <div className="mx-auto max-w-5xl px-4 pt-5 sm:px-6">
          <h1 className="text-3xl font-bold">LabelLens</h1>
          <p className="mt-1 text-lg text-slate-700">
            Check alcohol label photos against their applications, field by field.
          </p>
          <nav aria-label="Main" className="mt-4 flex gap-2">
            {TABS.map((tab) => (
              <a
                key={tab.view}
                href={tab.view === "batch" ? "?view=batch" : "/"}
                aria-current={view === tab.view ? "page" : undefined}
                onClick={(event) => {
                  event.preventDefault();
                  go(tab.view);
                }}
                className={`flex min-h-12 items-center rounded-t-lg border-b-4 px-5 text-lg font-semibold focus-visible:outline-4 focus-visible:outline-blue-700 ${
                  view === tab.view ? "border-blue-800 text-blue-900" : "border-transparent text-slate-700 hover:text-slate-900"
                }`}
              >
                {tab.label}
              </a>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">{view === "batch" ? <Batch /> : <Verify />}</main>
    </div>
  );
}
