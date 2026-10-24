import Verify from "./pages/Verify";

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b-2 border-slate-200 bg-white">
        <div className="mx-auto max-w-5xl px-4 py-5 sm:px-6">
          <h1 className="text-3xl font-bold">LabelLens</h1>
          <p className="mt-1 text-lg text-slate-700">
            Check an alcohol label photo against its application, field by field.
          </p>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        <Verify />
      </main>
    </div>
  );
}
