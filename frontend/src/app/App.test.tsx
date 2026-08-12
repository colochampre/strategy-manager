import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "@/app/App";

describe("App shell", () => {
  it("renders both navigation surfaces so large and small screens are covered", () => {
    render(<App />);

    // One sidebar (large screens) and one bottom bar (small screens).
    expect(screen.getAllByRole("navigation")).toHaveLength(2);
  });

  it("exposes every top-level section in both navigation surfaces", () => {
    render(<App />);

    for (const label of ["Dashboard", "Strategies", "Settings"]) {
      expect(screen.getAllByRole("link", { name: label })).toHaveLength(2);
    }
  });

  it("shows the dry-run indicator", () => {
    render(<App />);

    expect(screen.getByText("Dry run")).toBeInTheDocument();
  });
});
