import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { LabelResult, Status } from "../api/types";
import BatchTable, { toRow } from "./BatchTable";

function result(filename: string, status: Status, error: string | null = null): LabelResult {
  return {
    label_id: filename,
    filename,
    fields: error
      ? []
      : [
          {
            field: "brand_name",
            status,
            expected: `Brand ${filename}`,
            found: "x",
            reason: status === "pass" ? null : "Differs",
            ocr_confidence: 0.9,
          },
        ],
    timings_ms: {},
    preprocessing: [],
    ocr_confidence: 0.9,
    warnings: [],
    error,
    overall_status: error ? "fail" : status,
  };
}

const ROWS = [
  toRow(result("a.png", "pass")),
  toRow(result("b.png", "review")),
  toRow(result("c.png", "fail")),
  toRow(result("broken.png", "fail", "This file could not be read as an image")),
];

function fileOrder(): string[] {
  const body = screen.getAllByRole("rowgroup")[1];
  return within(body)
    .getAllByRole("row")
    .map((row) => within(row).getAllByRole("cell")[0].textContent ?? "");
}

test("fails come first by default and a row-level error explains itself", () => {
  render(<BatchTable rows={ROWS} onOpen={() => {}} />);
  expect(fileOrder().slice(0, 2).sort()).toEqual(["broken.png", "c.png"]);
  expect(fileOrder().slice(2)).toEqual(["b.png", "a.png"]);
  expect(screen.getByText("Could not check: This file could not be read as an image")).toBeInTheDocument();
});

test("filter chips show counts and narrow the table", async () => {
  const user = userEvent.setup();
  render(<BatchTable rows={ROWS} onOpen={() => {}} />);
  const review = screen.getByRole("button", { name: "Needs review (1)" });
  await user.click(review);
  expect(review).toHaveAttribute("aria-pressed", "true");
  expect(fileOrder()).toEqual(["b.png"]);
  await user.click(screen.getByRole("button", { name: "Fail (2)" }));
  expect(fileOrder()).toHaveLength(2);
});

test("search matches file name or brand", async () => {
  const user = userEvent.setup();
  render(<BatchTable rows={ROWS} onOpen={() => {}} />);
  await user.type(screen.getByLabelText("Search by file name or brand"), "brand a");
  expect(fileOrder()).toEqual(["a.png"]);
  await user.clear(screen.getByLabelText("Search by file name or brand"));
  await user.type(screen.getByLabelText("Search by file name or brand"), "nothing");
  expect(screen.getByText("No labels match this filter or search.")).toBeInTheDocument();
});

test("column headers sort", async () => {
  const user = userEvent.setup();
  render(<BatchTable rows={ROWS} onOpen={() => {}} />);
  await user.click(screen.getByRole("button", { name: /^File/ }));
  expect(fileOrder()).toEqual(["a.png", "b.png", "broken.png", "c.png"]);
  expect(screen.getByRole("columnheader", { name: /File/ })).toHaveAttribute("aria-sort", "ascending");
});

test("a row opens with the keyboard", async () => {
  const user = userEvent.setup();
  const onOpen = vi.fn();
  render(<BatchTable rows={ROWS} onOpen={onOpen} />);
  screen.getByRole("button", { name: "b.png" }).focus();
  await user.keyboard("{Enter}");
  expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ result: expect.objectContaining({ filename: "b.png" }) }));
});
