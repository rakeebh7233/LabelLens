import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { FieldResult } from "../api/types";
import ResultCard from "./ResultCard";

function field(overrides: Partial<FieldResult>): FieldResult {
  return {
    field: "brand_name",
    status: "pass",
    expected: "OLD TOM DISTILLERY",
    found: "OLD TOM DISTILLERY",
    reason: null,
    ocr_confidence: 0.95,
    ...overrides,
  };
}

function renderCard(result: FieldResult) {
  render(
    <ul>
      <ResultCard result={result} />
    </ul>,
  );
  return screen.getByRole("button", { name: /brand name/i });
}

test("a review card is open and shows both values side by side with the reason", () => {
  const toggle = renderCard(
    field({
      status: "review",
      expected: "STONE'S THROW",
      found: "Stone's Throw",
      reason: 'Label says "Stone\'s Throw", application says "STONE\'S THROW" - differs only in capitalization',
    }),
  );
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(within(toggle).getByText("Needs review")).toBeInTheDocument();
  expect(screen.getByText(/differs only in capitalization/)).toBeVisible();
  expect(screen.getByText("Application says").nextElementSibling).toHaveTextContent("STONE'S THROW");
  expect(screen.getByText("Label says").nextElementSibling).toHaveTextContent("Stone's Throw");
});

test("a fail card is open by default", () => {
  const toggle = renderCard(field({ status: "fail", found: "OTHER", reason: "Different brand" }));
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(within(toggle).getByText("Fail")).toBeInTheDocument();
});

test("a pass card starts closed and opens with the keyboard", async () => {
  const user = userEvent.setup();
  const toggle = renderCard(field({}));
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(screen.getByText("Application says")).not.toBeVisible();

  toggle.focus();
  await user.keyboard("{Enter}");
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("Application says")).toBeVisible();
});

test("a field missing from the label says so in words", () => {
  renderCard(field({ status: "fail", found: null, reason: "No brand name was found on the label" }));
  expect(screen.getByText("Not found on the label")).toBeInTheDocument();
});
