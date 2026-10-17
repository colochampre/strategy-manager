import { fireEvent, render, screen, within } from "@testing-library/react";
import { Copy } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { StatusButton } from "@/shared/ui/StatusButton";

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

  it("draws an optional icon left of the texts' grid, outside it, kept while the text changes", () => {
    const props = { texts: ["Copy", "Copied"], message: null, className: "button", icon: Copy };
    const { rerender } = render(<StatusButton {...props} shown="Copy" />);

    const button = screen.getByRole("button", { name: "Copy" });
    const svg = button.querySelector("svg");
    expect(svg).toHaveClass("lucide-copy", "shrink-0", "size-4");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    // Left of the grid, not inside it: the grid's width still follows the longest text alone.
    const grid = within(button).getByText("Copied").parentElement as HTMLElement;
    expect(classesOf(grid)).toContain("inline-grid");
    expect(grid.contains(svg)).toBe(false);
    expect(button.firstElementChild).toBe(svg);
    expect(classesOf(button)).toEqual(expect.arrayContaining(["inline-flex", "items-center", "gap-1.5"]));

    rerender(<StatusButton {...props} shown="Copied" />);

    expect(screen.getByRole("button", { name: "Copied" }).querySelector("svg")).toBe(svg);
  });

  it("renders without an icon exactly as before", () => {
    renderButton();

    const button = screen.getByRole("button", { name: "Copy" });
    expect(button.querySelector("svg")).toBeNull();
    expect(button.className).toBe("button");
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

  it("is the submit button of its form when asked, so Enter in a field presses it (task 13.5.3)", () => {
    const onSubmit = vi.fn((event: { preventDefault: () => void }) => event.preventDefault());
    render(
      <form onSubmit={onSubmit} noValidate>
        <input aria-label="field" />
        <StatusButton texts={["Save"]} shown="Save" message={null} className="button" submit />
      </form>,
    );

    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toHaveAttribute("type", "submit");
    fireEvent.click(button);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
