import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { LabelResult } from "../api/types";
import { EMPTY_FIELDS } from "../components/FieldForm";
import Verify, { blockedReason } from "./Verify";

const photo = () => new File(["fake"], "label.png", { type: "image/png" });

const passResult: LabelResult = {
  label_id: "abc",
  filename: "label.png",
  fields: [
    {
      field: "brand_name",
      status: "pass",
      expected: "OLD TOM DISTILLERY",
      found: "OLD TOM DISTILLERY",
      reason: null,
      ocr_confidence: 0.95,
    },
    {
      field: "government_warning",
      status: "fail",
      expected: "GOVERNMENT WARNING: ...",
      found: "Government Warning: ...",
      reason: 'The label has "Government Warning:" but the warning must begin "GOVERNMENT WARNING:"',
      ocr_confidence: 0.96,
    },
  ],
  timings_ms: { total: 1380 },
  preprocessing: [],
  ocr_confidence: 0.95,
  warnings: [],
  error: null,
  overall_status: "fail",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

async function fillEverything() {
  const user = userEvent.setup();
  render(<Verify />);
  await user.upload(screen.getByTestId("file-input"), photo());
  await user.type(screen.getByLabelText("Brand name"), "OLD TOM DISTILLERY");
  await user.type(screen.getByLabelText("Class / type"), "Bourbon");
  await user.type(screen.getByLabelText("Alcohol content"), "45%");
  await user.type(screen.getByLabelText("Net contents"), "750 mL");
  return user;
}

beforeAll(() => {
  // jsdom has no object URLs.
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("blockedReason names everything still missing", () => {
  expect(blockedReason(null, EMPTY_FIELDS)).toBe(
    "To check this label, add a label photo, the brand name, the class / type, the alcohol content and the net contents.",
  );
  expect(blockedReason(photo(), { ...EMPTY_FIELDS, brand_name: "x", class_type: "y", alcohol_content: "z" })).toBe(
    "To check this label, add the net contents.",
  );
  expect(
    blockedReason(photo(), { ...EMPTY_FIELDS, brand_name: "x", class_type: "y", alcohol_content: "z", net_contents: "w" }),
  ).toBeNull();
});

test("the check button stays disabled, with a reason, until the photo and fields exist", async () => {
  const user = userEvent.setup();
  render(<Verify />);
  const button = screen.getByRole("button", { name: "Check this label" });
  expect(button).toBeDisabled();
  expect(button).toHaveAccessibleDescription(/add a label photo, the brand name/);

  await user.upload(screen.getByTestId("file-input"), photo());
  expect(screen.getByAltText("Preview of label.png")).toBeInTheDocument();
  expect(button).toHaveAccessibleDescription(/add the brand name/);
});

test("an unsupported file type is refused in plain language", async () => {
  const user = userEvent.setup({ applyAccept: false });
  render(<Verify />);
  await user.upload(screen.getByTestId("file-input"), new File(["x"], "notes.pdf", { type: "application/pdf" }));
  expect(screen.getByRole("alert")).toHaveTextContent("notes.pdf is not a supported photo type");
});

test("a successful check shows the banner, field cards and elapsed time", async () => {
  const fetchMock = vi.fn().mockResolvedValue(json(passResult));
  vi.stubGlobal("fetch", fetchMock);
  const user = await fillEverything();

  const button = screen.getByRole("button", { name: "Check this label" });
  expect(button).toBeEnabled();
  await user.click(button);

  const banner = await screen.findByRole("heading", { level: 2, name: "Fail" });
  expect(banner).toHaveFocus();
  expect(screen.getByText("1 field does not match the application.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /government warning/i })).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("button", { name: /brand name/i })).toHaveAttribute("aria-expanded", "false");
  expect(screen.getByText(/Checked in \d+\.\d seconds/)).toBeInTheDocument();

  const body = fetchMock.mock.calls[0][1].body as FormData;
  expect(body.get("brand_name")).toBe("OLD TOM DISTILLERY");
  expect(body.get("government_warning")).toMatch(/^GOVERNMENT WARNING:/);
});

test("an unreadable photo shows a friendly error with a retry", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(json({ ...passResult, fields: [], error: "This file could not be read as an image." })),
  );
  const user = await fillEverything();
  await user.click(screen.getByRole("button", { name: "Check this label" }));

  expect(await screen.findByRole("heading", { name: "We could not read this photo" })).toHaveFocus();
  expect(screen.getByText("This file could not be read as an image.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
});

test("a server error shows its plain-language detail", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "label.png is larger than the 10 MB limit." }, 413)));
  const user = await fillEverything();
  await user.click(screen.getByRole("button", { name: "Check this label" }));

  expect(await screen.findByRole("heading", { name: "The label could not be checked" })).toBeInTheDocument();
  expect(screen.getByText("label.png is larger than the 10 MB limit.")).toBeInTheDocument();
});

test("a network error can be retried", async () => {
  const fetchMock = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch")).mockResolvedValue(json(passResult));
  vi.stubGlobal("fetch", fetchMock);
  const user = await fillEverything();
  await user.click(screen.getByRole("button", { name: "Check this label" }));

  expect(await screen.findByRole("heading", { name: "Could not reach the server" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByRole("heading", { level: 2, name: "Fail" })).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});
