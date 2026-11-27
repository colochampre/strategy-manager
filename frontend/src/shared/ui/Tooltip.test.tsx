import { fireEvent, render, screen } from "@testing-library/react";
import { Clock } from "lucide-react";
import { describe, expect, it } from "vitest";

import { IconTip, Tooltip } from "@/shared/ui/Tooltip";

function trigger(): HTMLElement {
  return screen.getByText("Hover me").parentElement as HTMLElement;
}

describe("Tooltip", () => {
  it("shows nothing until the trigger is hovered", () => {
    render(
      <Tooltip text="Explained">
        <span>Hover me</span>
      </Tooltip>,
    );

    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent.mouseEnter(trigger());
    expect(screen.getByRole("tooltip")).toHaveTextContent("Explained");
  });

  it("wraps its text inside its own box, whatever its trigger's cell inherits (L18)", () => {
    // A table cell holds its figures on one line in a monospaced face; the tip must not inherit either.
    render(
      <p className="whitespace-nowrap font-mono">
        <Tooltip text="A long explanation that has to break across several lines">
          <span>Hover me</span>
        </Tooltip>
      </p>,
    );

    fireEvent.mouseEnter(trigger());
    expect(screen.getByRole("tooltip")).toHaveClass("max-w-64", "whitespace-normal", "break-words", "text-left", "font-sans");
  });

  it("hides on mouse leave", () => {
    render(
      <Tooltip text="Explained">
        <span>Hover me</span>
      </Tooltip>,
    );

    fireEvent.mouseEnter(trigger());
    fireEvent.mouseLeave(trigger());
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("shows on keyboard focus and hides on blur", () => {
    render(
      <Tooltip text="Explained">
        <span>Hover me</span>
      </Tooltip>,
    );

    expect(trigger()).toHaveAttribute("tabindex", "0");
    fireEvent.focus(trigger());
    expect(screen.getByRole("tooltip")).toHaveTextContent("Explained");
    fireEvent.blur(trigger());
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("hides on Escape while the trigger keeps focus", () => {
    render(
      <Tooltip text="Explained">
        <span>Hover me</span>
      </Tooltip>,
    );

    fireEvent.focus(trigger());
    fireEvent.keyDown(trigger(), { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("points the trigger at the tip with aria-describedby only while it is shown", () => {
    render(
      <Tooltip text="Explained">
        <span>Hover me</span>
      </Tooltip>,
    );

    expect(trigger()).not.toHaveAttribute("aria-describedby");
    fireEvent.focus(trigger());
    expect(trigger()).toHaveAttribute("aria-describedby", screen.getByRole("tooltip").id);
  });
});

describe("IconTip", () => {
  it("keeps the label as the icon's accessible name and draws the glyph hidden", () => {
    const { container } = render(<IconTip icon={Clock} label="active 12 days" />);

    expect(screen.getByRole("img", { name: "active 12 days" })).toBeInTheDocument();
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("is lighter and a little larger than the info button's 16 px grey glyph, whatever text it sits in", () => {
    const { container } = render(
      <span className="text-ink-3">
        <IconTip icon={Clock} label="active 12 days" />
      </span>,
    );

    expect(screen.getByRole("img", { name: "active 12 days" })).toHaveClass("text-ink-2");
    expect(container.querySelector("svg")).toHaveClass("size-4.5");
  });

  it("explains itself with the same words on hover", () => {
    render(<IconTip icon={Clock} label="active 12 days" />);

    fireEvent.mouseEnter(screen.getByRole("img", { name: "active 12 days" }).parentElement as HTMLElement);
    expect(screen.getByRole("tooltip")).toHaveTextContent("active 12 days");
  });

  it("is not described by its tip, which only repeats its name", () => {
    render(<IconTip icon={Clock} label="active 12 days" />);
    const trigger = screen.getByRole("img", { name: "active 12 days" }).parentElement as HTMLElement;

    fireEvent.focus(trigger);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    expect(trigger).not.toHaveAttribute("aria-describedby");
  });
});

describe("Tooltip layout class", () => {
  it("is an inline flex box by default and takes the class it is given instead (L.7)", () => {
    const { rerender } = render(
      <Tooltip text="Explained">
        <span>Hover me</span>
      </Tooltip>,
    );
    expect(trigger()).toHaveClass("relative", "inline-flex");

    rerender(
      <Tooltip text="Explained" className="flex w-full">
        <span>Hover me</span>
      </Tooltip>,
    );

    expect(trigger()).toHaveClass("relative", "flex", "w-full");
    expect(trigger()).not.toHaveClass("inline-flex");
  });
});

describe("Tooltip: the hybrid of L63/L64", () => {
  function tip(): HTMLElement {
    return screen.getByRole("tooltip");
  }

  it("a click on the trigger pins the tip: leaving and blur do not hide it, a press outside does", () => {
    render(
      <>
        <Tooltip text="Explained">
          <span>Hover me</span>
        </Tooltip>
        <p>Elsewhere</p>
      </>,
    );
    fireEvent.mouseEnter(trigger());
    fireEvent.click(trigger());

    fireEvent.mouseLeave(trigger());
    fireEvent.blur(trigger());
    expect(tip()).toHaveTextContent("Explained");

    fireEvent.mouseDown(screen.getByText("Elsewhere"));
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("a tap pins it with no pointer before it, and a press inside the tip keeps it", () => {
    render(
      <Tooltip text="Explained">
        <span>Hover me</span>
      </Tooltip>,
    );
    fireEvent.click(trigger());
    fireEvent.mouseDown(tip());
    expect(tip()).toBeInTheDocument();
  });

  it("a click on a pinned tip's trigger hides it, even with the pointer still on it", () => {
    render(
      <Tooltip text="Explained">
        <span>Hover me</span>
      </Tooltip>,
    );
    fireEvent.mouseEnter(trigger());
    fireEvent.click(trigger());

    fireEvent.click(trigger());

    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("Escape hides a pinned tip and focus stays on the trigger", () => {
    render(
      <Tooltip text="Explained">
        <span>Hover me</span>
      </Tooltip>,
    );
    trigger().focus();
    fireEvent.click(trigger());

    fireEvent.keyDown(trigger(), { key: "Escape" });

    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(trigger()).toHaveFocus();
  });

  it("a click on a control the tip wraps is the control's, and does not pin the tip", () => {
    render(
      <Tooltip text="Explained" tabbable={false}>
        <button type="button">Act</button>
      </Tooltip>,
    );
    const wrapper = screen.getByRole("button", { name: "Act" }).parentElement as HTMLElement;
    fireEvent.mouseEnter(wrapper);
    fireEvent.click(screen.getByRole("button", { name: "Act" }));

    fireEvent.mouseLeave(wrapper);

    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("the tip takes the pointer, and a bridge over its gap keeps the pointer inside on the way to it", () => {
    render(
      <>
        <Tooltip text="Above">
          <span>Hover me</span>
        </Tooltip>
      </>,
    );
    fireEvent.mouseEnter(trigger());

    expect(tip()).not.toHaveClass("pointer-events-none");
    expect(tip().className).toMatch(/(^|\s)before:absolute(\s|$)/);
    expect(tip().className).toMatch(/(^|\s)before:-bottom-1(\s|$)/);
  });

  it("below its trigger, the bridge reaches up instead", () => {
    render(
      <Tooltip text="Below" placement="below">
        <span>Hover me</span>
      </Tooltip>,
    );
    fireEvent.mouseEnter(trigger());

    expect(tip().className).toMatch(/(^|\s)before:-top-1(\s|$)/);
  });
});
