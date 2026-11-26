import { fireEvent, render, screen } from "@testing-library/react";
import { Copy } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { IconButton } from "@/shared/ui/IconButton";

const classesOf = (element: Element) => element.className.split(/\s+/);

describe("IconButton", () => {
  it("is a square icon button named by its label, with the icon hidden from assistive technology", () => {
    render(<IconButton label="Copy" icon={Copy} onClick={() => undefined} />);

    const button = screen.getByRole("button", { name: "Copy" });
    expect(classesOf(button)).toEqual(expect.arrayContaining(["size-11", "shrink-0"]));
    expect(button).toHaveTextContent("");
    expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(button).toHaveAttribute("type", "button");
  });

  it("shows its label as a tooltip on hover and on keyboard focus, without describing the button twice", () => {
    render(<IconButton label="Copy" icon={Copy} onClick={() => undefined} />);
    const button = screen.getByRole("button", { name: "Copy" });

    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.mouseEnter(button.parentElement as HTMLElement);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Copy");
    expect(button.parentElement).not.toHaveAttribute("aria-describedby");
    fireEvent.mouseLeave(button.parentElement as HTMLElement);
    fireEvent.focus(button);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Copy");
  });

  it("takes keyboard focus on the button alone, not on a wrapper", () => {
    render(<IconButton label="Copy" icon={Copy} onClick={() => undefined} />);

    expect(screen.getByRole("button", { name: "Copy" }).parentElement).not.toHaveAttribute("tabindex");
  });

  it("calls onClick, and not when disabled", () => {
    const onClick = vi.fn();
    const { rerender } = render(<IconButton label="Copy" icon={Copy} onClick={onClick} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(onClick).toHaveBeenCalledTimes(1);

    rerender(<IconButton label="Copy" icon={Copy} onClick={onClick} disabled />);
    expect(screen.getByRole("button", { name: "Copy" })).toBeDisabled();
  });

  it("submits its form when asked", () => {
    render(<IconButton label="Save" icon={Copy} submit />);

    expect(screen.getByRole("button", { name: "Save" })).toHaveAttribute("type", "submit");
  });

  it("has a danger look that keeps the loss colour", () => {
    render(<IconButton label="Delete" icon={Copy} tone="danger" onClick={() => undefined} />);

    expect(classesOf(screen.getByRole("button", { name: "Delete" }))).toEqual(
      expect.arrayContaining(["border-loss", "text-loss"]),
    );
  });

  it("is 32 px in a row's actions (ex6), named by a title and with no floating tip", () => {
    render(<IconButton label="Copy" icon={Copy} size="sm" onClick={() => undefined} />);
    const button = screen.getByRole("button", { name: "Copy" });

    expect(classesOf(button)).toEqual(expect.arrayContaining(["size-8", "shrink-0"]));
    expect(classesOf(button)).not.toContain("size-11");
    expect(button).toHaveAttribute("title", "Copy");
    fireEvent.mouseEnter(button.parentElement as HTMLElement);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("has a primary look for a Save", () => {
    render(<IconButton label="Save" icon={Copy} tone="primary" onClick={() => undefined} />);

    // The green outline every green button wears (L26), not a filled green.
    const classes = classesOf(screen.getByRole("button", { name: "Save" }));
    expect(classes).toEqual(expect.arrayContaining(["border-gain/45", "text-gain-bright", "bg-transparent"]));
    expect(classes).not.toContain("bg-gain");
  });
});

describe("IconButton, name and ref", () => {
  it("can be named more fully than its tip says, and gives the button to a ref", () => {
    let held: HTMLButtonElement | null = null;
    render(
      <IconButton
        label="Delete key"
        name="Delete key Binance"
        icon={Copy}
        ref={(node) => {
          held = node;
        }}
      />,
    );

    const button = screen.getByRole("button", { name: "Delete key Binance" });
    expect(held).toBe(button);
    fireEvent.mouseEnter(button.parentElement as HTMLElement);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Delete key");
    expect(screen.getByRole("tooltip")).not.toHaveTextContent("Binance");
  });
});
