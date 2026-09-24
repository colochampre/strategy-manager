import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { App } from "@/app/App";

describe("App shell", () => {
  beforeEach(() => {
    window.location.hash = "";
  });

  it("renders both navigation surfaces so large and small screens are covered", () => {
    render(<App />);

    // One sidebar (large screens) and one bottom bar (small screens).
    expect(screen.getAllByRole("navigation")).toHaveLength(2);
  });

  it("exposes every top-level section in both navigation surfaces", () => {
    render(<App />);

    for (const label of ["Dashboard", "Strategies", "Settings", "Bookings"]) {
      expect(screen.getAllByRole("link", { name: label })).toHaveLength(2);
    }
  });

  it("shows the dry-run indicator", () => {
    render(<App />);

    expect(screen.getByText("Dry run")).toBeInTheDocument();
  });
});

describe("App navigation", () => {
  beforeEach(() => {
    window.location.hash = "";
  });

  it("defaults the active section to dashboard when there is no hash", () => {
    render(<App />);

    expect(screen.getAllByRole("link", { name: "Dashboard" })[0]).toHaveClass("bg-surface-800");
  });

  it("seeds the active section from the current location hash", () => {
    window.location.hash = "#bookings";

    render(<App />);

    expect(screen.getAllByRole("link", { name: "Bookings" })[0]).toHaveClass("bg-surface-800");
    expect(screen.getAllByRole("link", { name: "Dashboard" })[0]).not.toHaveClass("bg-surface-800");
  });

  it("falls back to dashboard for an unrecognised hash", () => {
    window.location.hash = "#not-a-real-section";

    render(<App />);

    expect(screen.getAllByRole("link", { name: "Dashboard" })[0]).toHaveClass("bg-surface-800");
  });

  it("updates the active section when the hash changes after mount", () => {
    render(<App />);
    expect(screen.getAllByRole("link", { name: "Dashboard" })[0]).toHaveClass("bg-surface-800");

    window.location.hash = "#bookings";
    fireEvent(window, new Event("hashchange"));

    expect(screen.getAllByRole("link", { name: "Bookings" })[0]).toHaveClass("bg-surface-800");
  });
});
