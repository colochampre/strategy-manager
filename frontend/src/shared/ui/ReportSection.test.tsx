import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReportSection } from "@/shared/ui/ReportSection";

describe("ReportSection", () => {
  it("renders its children inside the section", () => {
    render(
      <ReportSection>
        <p>Inside</p>
      </ReportSection>,
    );

    expect(screen.getByTestId("report-section")).toContainElement(screen.getByText("Inside"));
  });

  it("draws the strategy card's frame from md (768 px) up", () => {
    render(<ReportSection>x</ReportSection>);

    const classes = screen.getByTestId("report-section").className.split(/\s+/);
    for (const frame of ["md:rounded-md", "md:border", "md:border-rule", "md:bg-panel", "md:px-4", "md:py-3"]) {
      expect(classes).toContain(frame);
    }
    expect(classes).toContain("min-w-0");
  });

  it("applies no frame class below md: every class but min-w-0 is md-prefixed", () => {
    render(<ReportSection>x</ReportSection>);

    const classes = screen.getByTestId("report-section").className.split(/\s+/).filter((name) => name !== "");
    const unprefixed = classes.filter((name) => !name.startsWith("md:"));
    expect(unprefixed).toEqual(["min-w-0"]);
  });
});
