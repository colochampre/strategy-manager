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
