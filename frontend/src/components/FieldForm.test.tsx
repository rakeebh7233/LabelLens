import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { STANDARD_GOVERNMENT_WARNING, type ApplicationFields } from "../api/types";
import FieldForm, { EMPTY_FIELDS, missingFields } from "./FieldForm";

function Harness() {
  const [fields, setFields] = useState<ApplicationFields>(EMPTY_FIELDS);
  return <FieldForm fields={fields} onChange={setFields} />;
}

test("missingFields lists blank required fields in form order", () => {
  expect(missingFields(EMPTY_FIELDS)).toEqual(["brand name", "class / type", "alcohol content", "net contents"]);
  expect(missingFields({ ...EMPTY_FIELDS, brand_name: "Old Tom", net_contents: "  " })).toEqual([
    "class / type",
    "alcohol content",
    "net contents",
  ]);
});

test("every field has a visible label", () => {
  render(<Harness />);
  for (const name of ["Brand name", "Class / type", "Alcohol content", "Net contents"]) {
    expect(screen.getByLabelText(name)).toBeInTheDocument();
  }
});

test("the warning is prefilled and hidden behind Edit warning text", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  const toggle = screen.getByRole("button", { name: "Edit warning text" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(screen.getByLabelText("Warning text", { selector: "textarea" })).not.toBeVisible();

  await user.click(toggle);
  const textarea = screen.getByLabelText("Warning text");
  expect(textarea).toBeVisible();
  expect(textarea).toHaveValue(STANDARD_GOVERNMENT_WARNING);

  await user.type(textarea, " extra");
  expect(screen.getByText("Using edited warning text.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Reset to the standard text" }));
  expect(textarea).toHaveValue(STANDARD_GOVERNMENT_WARNING);
});
