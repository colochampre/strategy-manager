import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InlineStatus } from "@/features/strategies/InlineStatus";

// A live region that appears together with its text is not reliably announced, so the region is always
// in the document and empty until it has something to say (design § D).

describe("InlineStatus", () => {
  it("is in the document before it has anything to say, empty", () => {
    render(<InlineStatus message={null} />);

    const region = screen.queryByRole("status");
    expect(region).toBeInTheDocument();
    expect(region).toBeEmptyDOMElement();
  });

  it("announces politely", () => {
    render(<InlineStatus message={null} />);

    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
  });

  it("shows its message", () => {
    render(<InlineStatus message="Saved" />);

    expect(within(screen.getByRole("status")).getByText("Saved")).toBeInTheDocument();
  });

  it("is the same element before and after it has something to say", () => {
    const { rerender } = render(<InlineStatus message={null} />);
    const before = screen.getByRole("status");

    rerender(<InlineStatus message="Copied" />);
    expect(screen.getByRole("status")).toBe(before);
    expect(before).toHaveTextContent("Copied");

    rerender(<InlineStatus message={null} />);
    expect(screen.getByRole("status")).toBe(before);
    expect(before).toBeEmptyDOMElement();
  });

  it("the default tone is neutral ink-2, never gain or loss", () => {
    render(<InlineStatus message="Saved" />);

    const region = screen.getByRole("status");
    expect(region.className).toContain("text-ink-2");
    expect(region.className).not.toContain("text-gain");
    expect(region.className).not.toContain("text-loss");
  });

  it("the default tone is only announced: visually hidden, the control shows the news itself", () => {
    render(<InlineStatus message="Saved" />);

    expect(screen.getByRole("status").className.split(/\s+/)).toContain("sr-only");
  });

  it("a failure is a visible text: it is not visually hidden", () => {
    render(<InlineStatus message="Could not copy." tone="failure" />);

    expect(screen.getByRole("status").className.split(/\s+/)).not.toContain("sr-only");
  });

  it("a failure tone is loss, never gain", () => {
    render(<InlineStatus message="Could not copy." tone="failure" />);

    const region = screen.getByRole("status");
    expect(region.className).toContain("text-loss");
    expect(region.className).not.toContain("text-gain");
    expect(region.className).not.toContain("text-ink-2");
  });

  it("two instances are independent", () => {
    render(
      <>
        <InlineStatus message="Saved" />
        <InlineStatus message={null} />
      </>,
    );

    const [first, second] = screen.getAllByRole("status");
    expect(first).toHaveTextContent("Saved");
    expect(second).toBeEmptyDOMElement();
  });
});
