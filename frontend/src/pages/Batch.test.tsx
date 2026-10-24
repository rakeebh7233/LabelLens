import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { BatchJob, JobState, LabelResult } from "../api/types";
import Batch from "./Batch";

const { startBatch } = vi.hoisted(() => ({ startBatch: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  startBatch,
}));

const HEADER = "filename,brand_name,class_type,alcohol_content,net_contents,government_warning\n";
const photo = (name: string) => new File(["x"], name, { type: "image/png" });
const csv = (body: string) => new File([HEADER + body], "applications.csv", { type: "text/csv" });

function label(filename: string, error: string | null = null): LabelResult {
  return {
    label_id: filename,
    filename,
    fields: error
      ? []
      : [{ field: "brand_name", status: "pass", expected: "Old Tom", found: "Old Tom", reason: null, ocr_confidence: 0.9 }],
    timings_ms: { total: 900 },
    preprocessing: [],
    ocr_confidence: 0.9,
    warnings: [],
    error,
    overall_status: error ? "fail" : "pass",
  };
}

function job(state: JobState, completed: number, total: number, results: LabelResult[]): BatchJob {
  return {
    job_id: "job1",
    state,
    created_at: "2026-10-23T00:00:00Z",
    progress: { total, completed, passed: completed, review: 0, failed: 0 },
    results,
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  window.history.replaceState(null, "", "/?view=batch");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  startBatch.mockReset();
});

test("start is explained until photos and a spreadsheet are added", async () => {
  const user = userEvent.setup();
  render(<Batch />);
  const start = screen.getByRole("button", { name: "Start checking" });
  expect(start).toHaveAccessibleDescription("To start, add the label photos.");
  await user.upload(screen.getByTestId("photos-input"), [photo("a.png")]);
  expect(start).toHaveAccessibleDescription("To start, add the spreadsheet (CSV file).");
  await user.upload(screen.getByTestId("manifest-input"), csv("a.png,Old Tom,Bourbon,45%,750 mL,\n"));
  expect(await screen.findByRole("button", { name: "Start checking 1 label" })).toBeEnabled();
  expect(screen.getByRole("link", { name: "Download CSV template" })).toHaveAttribute("download");
});

test("a spreadsheet with missing columns is refused before upload", async () => {
  const user = userEvent.setup();
  render(<Batch />);
  await user.upload(
    screen.getByTestId("manifest-input"),
    new File(["filename,brand_name\na.png,X\n"], "m.csv", { type: "text/csv" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("The spreadsheet is missing these columns");
});

test("mismatches are listed and the agent can continue with the matches", async () => {
  startBatch.mockResolvedValue({ job_id: "job1", total: 1 });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(job("done", 1, 1, [label("a.png")]))));
  const user = userEvent.setup();
  render(<Batch />);
  await user.upload(screen.getByTestId("photos-input"), [photo("a.png"), photo("stray.png")]);
  await user.upload(
    screen.getByTestId("manifest-input"),
    csv("a.png,Old Tom,Bourbon,45%,750 mL,\nmissing.png,X,Y,40%,1 L,\n"),
  );

  expect(await screen.findByText("1 photo has no row in the spreadsheet:")).toBeInTheDocument();
  expect(screen.getByText("stray.png")).toBeInTheDocument();
  expect(screen.getByText("1 spreadsheet row has no photo:")).toBeInTheDocument();
  expect(screen.getByText("missing.png")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Continue with the 1 match" }));
  const [images, manifest] = startBatch.mock.calls[0] as [File[], File];
  expect(images.map((f) => f.name)).toEqual(["a.png"]);
  expect(await manifest.text()).not.toContain("missing.png");
  expect(window.location.search).toContain("job=job1");
  expect(await screen.findByRole("heading", { name: "Checking finished" })).toBeInTheDocument();
});

test("a running batch fills the table, shows progress and survives a refresh via the URL", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  window.history.replaceState(null, "", "/?view=batch&job=job1");
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(json(job("running", 1, 3, [label("a.png")])))
    .mockResolvedValueOnce(json(job("done", 3, 3, [label("b.png"), label("bad.png", "This file could not be read as an image")])));
  vi.stubGlobal("fetch", fetchMock);
  render(<Batch />);

  expect(await screen.findByText("1 of 3 checked")).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "1");
  expect(screen.getByRole("button", { name: "Download results (CSV)" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "a.png" })).toBeInTheDocument();

  await vi.advanceTimersByTimeAsync(1500);
  expect(await screen.findByRole("heading", { name: "Checking finished" })).toBeInTheDocument();
  expect(fetchMock.mock.calls[1][0]).toBe("/api/batch/job1?since=1");
  expect(screen.getByText("Could not check: This file could not be read as an image")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Download results (CSV)" })).toHaveAttribute(
    "href",
    "/api/batch/job1/export.csv",
  );
});

test("clicking a row opens the detail panel and Escape closes it", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(job("done", 1, 1, [label("a.png")]))));
  window.history.replaceState(null, "", "/?view=batch&job=job1");
  const user = userEvent.setup();
  render(<Batch />);
  await user.click(await screen.findByRole("button", { name: "a.png" }));
  const panel = screen.getByRole("dialog", { name: "a.png" });
  expect(within(panel).getByRole("heading", { name: "Pass" })).toBeInTheDocument();
  expect(within(panel).getByRole("button", { name: "Close" })).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "a.png" })).toHaveFocus();
});

test("stop checking cancels the job after confirmation", async () => {
  vi.stubGlobal("confirm", vi.fn(() => true));
  const fetchMock = vi.fn((_url: string, init?: RequestInit) =>
    Promise.resolve(
      init?.method === "DELETE" ? json(job("cancelled", 1, 3, [])) : json(job("running", 1, 3, [label("a.png")])),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState(null, "", "/?view=batch&job=job1");
  const user = userEvent.setup();
  render(<Batch />);
  await user.click(await screen.findByRole("button", { name: "Stop checking" }));
  expect(await screen.findByRole("heading", { name: "Checking stopped" })).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/batch/job1", { method: "DELETE" });
  expect(screen.getByRole("link", { name: "Download results (CSV)" })).toBeInTheDocument();
});

test("an expired job id explains itself and offers a new batch", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(json({ detail: "This batch was not found. Results are kept for 60 minutes." }, 404)),
  );
  window.history.replaceState(null, "", "/?view=batch&job=old");
  const user = userEvent.setup();
  render(<Batch />);
  expect(await screen.findByText(/This batch was not found/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Start a new batch" }));
  await waitFor(() => expect(window.location.search).toBe("?view=batch"));
  expect(screen.getByRole("heading", { name: "1. Label photos" })).toBeInTheDocument();
});
