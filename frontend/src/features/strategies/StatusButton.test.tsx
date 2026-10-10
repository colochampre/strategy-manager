import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StatusButton } from "@/features/strategies/StatusButton";

const classesOf = (element: Element) => element.className.split(/\s+/);

function renderButton(props: Partial<Parameters<typeof StatusButton>[0]> = {}) {
  const onClick = vi.fn();
  render(
    <StatusButton
      texts={["Copy", "Copied"]}
      shown="Copy"
      message={null}
      onClick={onClick}
      className="button"
      {...props}
    />,
  );
  return { onClick };
}

describe("StatusButton", () => {
  it("holds every text in the button, and only the shown one is in its accessible name", () => {
    renderButton();

    const button = screen.getByRole("button", { name: "Copy" });
    expect(within(button).getByText("Copied")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copied" })).toBeNull();
  });

  it("hides a text that is not shown from sight and from assistive technology, and not the shown one", () => {
    renderButton({ shown: "Copied" });

    const button = screen.getByRole("button", { name: "Copied" });
    const hidden = within(button).getByText("Copy");
    const shown = within(button).getByText("Copied");
    expect(hidden).toHaveAttribute("aria-hidden", "true");
    expect(classesOf(hidden)).toContain("invisible");
    expect(shown).not.toHaveAttribute("aria-hidden");
    expect(classesOf(shown)).not.toContain("invisible");
  });

  it("puts all the texts in one grid cell, so the button has the width of the longest", () => {
    renderButton({ texts: ["Save share", "Saving…", "Saved"], shown: "Saving…" });

    const button = screen.getByRole("button", { name: "Saving…" });
    for (const text of ["Save share", "Saving…", "Saved"]) {
      const cell = within(button).getByText(text);
      expect(classesOf(cell)).toEqual(expect.arrayContaining(["col-start-1", "row-start-1"]));
      expect(classesOf(cell.parentElement as HTMLElement)).toContain("inline-grid");
    }
  });

  it("follows the shown text when it changes, with the same button", () => {
    const props = { texts: ["Copy", "Copied"], message: null, onClick: () => undefined, className: "button" };
    const { rerender } = render(<StatusButton {...props} shown="Copy" />);
    const before = screen.getByRole("button");

    rerender(<StatusButton {...props} shown="Copied" />);

    expect(screen.getByRole("button", { name: "Copied" })).toBe(before);
  });

  it("is followed by its status region, always mounted, which says the message", () => {
    const props = { texts: ["Copy", "Copied"], shown: "Copy", onClick: () => undefined, className: "button" };
    const { rerender } = render(<StatusButton {...props} message={null} />);
    const status = screen.getByRole("status");
    expect(status).toBeEmptyDOMElement();
    expect(screen.getByRole("button").compareDocumentPosition(status) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    rerender(<StatusButton {...props} message="Copied" />);

    expect(screen.getByRole("status")).toBe(status);
    expect(status).toHaveTextContent("Copied");
  });

  it("passes a failure tone to the region, which is then a visible text", () => {
    renderButton({ message: "Could not copy", tone: "failure" });

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Could not copy");
    expect(classesOf(status)).toContain("text-loss");
    expect(classesOf(status)).not.toContain("sr-only");
  });

  it("calls onClick when pressed", () => {
    const first = renderButton();
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(first.onClick).toHaveBeenCalledTimes(1);
  });

  it("is a button that does not submit a form, and honours disabled", () => {
    renderButton({ disabled: true });

    const button = screen.getByRole("button", { name: "Copy" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("type", "button");
  });
});
