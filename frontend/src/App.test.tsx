import { render, screen } from "@testing-library/react";
import App from "./App";

test("renders the verify page", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "LabelLens" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Check this label" })).toBeInTheDocument();
});
