import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";
import { pressEnter, pressSpace, pressTab } from "@/test/keyboard";

interface RowProps {
  label: string;
  text: string;
}

/** One information button with its text under it, the way a control places the two parts. */
function Row({ label, text }: RowProps) {
  const disclosure = useInfoDisclosure();
  return (
    <div>
      <InfoButton disclosure={disclosure} label={label} />
      <InfoText disclosure={disclosure}>
        <p>{text}</p>
      </InfoText>
    </div>
  );
}

const SHARE = { label: "About the share of the pool", text: "The share is a part of the pool's total balance." };
const AMOUNT = { label: "About this amount and what is not checked", text: "The amount is an estimate." };

function shareButton(): HTMLElement {
  return screen.getByRole("button", { name: SHARE.label });
}

function amountButton(): HTMLElement {
  return screen.getByRole("button", { name: AMOUNT.label });
}

describe("InfoDisclosure", () => {
  it("is closed at mount and no explanation is in the document", () => {
    render(<Row {...SHARE} />);

    expect(shareButton()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(SHARE.text)).toBeNull();
  });

  it("activating the button shows the text and aria-expanded is true", () => {
    render(<Row {...SHARE} />);

    fireEvent.click(shareButton());

    expect(screen.queryByText(SHARE.text)).toBeInTheDocument();
    expect(shareButton()).toHaveAttribute("aria-expanded", "true");
  });

  it("activating again closes it", () => {
    render(<Row {...SHARE} />);

    fireEvent.click(shareButton());
    expect(screen.queryByText(SHARE.text)).toBeInTheDocument();
    fireEvent.click(shareButton());

    expect(screen.queryByText(SHARE.text)).toBeNull();
    expect(shareButton()).toHaveAttribute("aria-expanded", "false");
  });

  it("Enter and Space toggle it", () => {
    render(<Row {...SHARE} />);
    shareButton().focus();

    pressEnter();
    expect(screen.queryByText(SHARE.text)).toBeInTheDocument();
    pressEnter();
    expect(screen.queryByText(SHARE.text)).toBeNull();
    pressSpace();
    expect(screen.queryByText(SHARE.text)).toBeInTheDocument();
    pressSpace();
    expect(screen.queryByText(SHARE.text)).toBeNull();
  });

  it("Escape on the button closes it and leaves focus on the button", () => {
    render(<Row {...SHARE} />);
    fireEvent.click(shareButton());
    expect(screen.queryByText(SHARE.text)).toBeInTheDocument();
    shareButton().focus();

    fireEvent.keyDown(shareButton(), { key: "Escape" });

    expect(screen.queryByText(SHARE.text)).toBeNull();
    expect(shareButton()).toHaveAttribute("aria-expanded", "false");
    expect(shareButton()).toHaveFocus();
  });

  it("Escape inside the text closes it and leaves focus on the button", () => {
    render(<Row {...SHARE} />);
    fireEvent.click(shareButton());
    expect(screen.queryByText(SHARE.text)).toBeInTheDocument();
    (document.activeElement as HTMLElement | null)?.blur();
    expect(shareButton()).not.toHaveFocus();

    fireEvent.keyDown(screen.getByText(SHARE.text), { key: "Escape" });

    expect(screen.queryByText(SHARE.text)).toBeNull();
    expect(shareButton()).toHaveFocus();
  });

  it("another key does not close it", () => {
    render(<Row {...SHARE} />);
    fireEvent.click(shareButton());

    fireEvent.keyDown(screen.getByText(SHARE.text), { key: "a" });
    fireEvent.keyDown(shareButton(), { key: "ArrowDown" });

    expect(screen.queryByText(SHARE.text)).toBeInTheDocument();
  });

  it("tabbing away from an open explanation leaves it open", () => {
    render(
      <>
        <Row {...SHARE} />
        <button type="button">Elsewhere</button>
      </>,
    );
    fireEvent.click(shareButton());
    shareButton().focus();

    // `pressTab` moves focus without going through an event helper, so React is told to flush its updates.
    act(() => {
      pressTab();
    });

    expect(screen.getByRole("button", { name: "Elsewhere" })).toHaveFocus();
    expect(screen.queryByText(SHARE.text)).toBeInTheDocument();
    expect(shareButton()).toHaveAttribute("aria-expanded", "true");
  });

  it("a press outside closes it, and a press on the button or inside the box does not", () => {
    render(
      <>
        <Row {...SHARE} />
        <p>Elsewhere</p>
      </>,
    );
    fireEvent.click(shareButton());

    fireEvent.mouseDown(screen.getByText(SHARE.text));
    expect(screen.queryByText(SHARE.text)).toBeInTheDocument();
    fireEvent.mouseDown(shareButton());
    expect(screen.queryByText(SHARE.text)).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByText("Elsewhere"));

    expect(screen.queryByText(SHARE.text)).toBeNull();
    expect(shareButton()).toHaveAttribute("aria-expanded", "false");
  });

  it("an outside press does nothing while it is closed, and the listener is gone after unmount", () => {
    const { unmount } = render(<Row {...SHARE} />);
    fireEvent.mouseDown(document.body);
    expect(shareButton()).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(shareButton());
    unmount();

    expect(() => fireEvent.mouseDown(document.body)).not.toThrow();
  });

  it("opens the text in a floating box anchored to the button, not inline where the text is written", () => {
    render(<Row {...SHARE} />);
    fireEvent.click(shareButton());

    const box = document.getElementById(shareButton().getAttribute("aria-controls") ?? "");
    expect(box).toContainElement(screen.getByText(SHARE.text));
    expect(box?.className).toMatch(/(^|\s)absolute(\s|$)/);
    expect(box?.className).toMatch(/(^|\s)top-full(\s|$)/);
    expect(box?.className).toMatch(/(^|\s)z-\d+(\s|$)/);
    expect(box).toHaveClass("border", "border-rule", "bg-panel-2");
    // The anchor holds the button and the box together, so the box is placed against the button.
    expect(box?.parentElement?.className).toMatch(/(^|\s)relative(\s|$)/);
    expect(box?.parentElement).toContainElement(shareButton());
    expect(box).not.toHaveAttribute("style");
  });

  it.each([
    ["in the middle of the screen, it is centred under the button", 700, ["left-1/2", "-translate-x-1/2"], ["right-0", "left-0"]],
    ["near the right edge, it lines up with the button's right edge", 1380, ["right-0"], ["left-1/2", "left-0"]],
    ["near the left edge, it lines up with the button's left edge", 40, ["left-0"], ["left-1/2", "right-0"]],
  ])("the box stays on screen: %s", (_case, centre, present, absent) => {
    render(<Row {...SHARE} />);
    const width = 1422;
    Object.defineProperty(document.documentElement, "clientWidth", { configurable: true, value: width });
    shareButton().getBoundingClientRect = () => new DOMRect(centre - 22, 100, 44, 44);
    fireEvent.click(shareButton());

    const box = document.getElementById(shareButton().getAttribute("aria-controls") ?? "");
    expect(box).toHaveClass(...present);
    for (const name of absent) expect(box).not.toHaveClass(name);
  });

  it("the box fades in with the tip animation, by motion-safe only", () => {
    render(<Row {...SHARE} />);
    fireEvent.click(shareButton());

    const box = document.getElementById(shareButton().getAttribute("aria-controls") ?? "");
    expect(box?.className).toMatch(/(^|\s)motion-safe:animate-tip-in(\s|$)/);
    expect(box?.className).not.toMatch(/(^|\s)animate-tip-in(\s|$)/);
  });

  it("two disclosures open together and closing one leaves the other", () => {
    render(
      <>
        <Row {...SHARE} />
        <Row {...AMOUNT} />
      </>,
    );

    fireEvent.click(shareButton());
    fireEvent.click(amountButton());
    expect(screen.queryByText(SHARE.text)).toBeInTheDocument();
    expect(screen.queryByText(AMOUNT.text)).toBeInTheDocument();

    fireEvent.click(shareButton());
    expect(screen.queryByText(SHARE.text)).toBeNull();
    expect(screen.queryByText(AMOUNT.text)).toBeInTheDocument();
    expect(amountButton()).toHaveAttribute("aria-expanded", "true");
  });

  it("aria-controls names an element present while closed, and the paragraphs are rendered only while open", () => {
    render(<Row {...SHARE} />);
    const id = shareButton().getAttribute("aria-controls");
    expect(id).toBeTruthy();

    const container = document.getElementById(id ?? "");
    expect(container).toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();

    fireEvent.click(shareButton());
    expect(document.getElementById(id ?? "")).toBe(container);
    expect(container).toHaveTextContent(SHARE.text);
  });

  it("two disclosures name two different containers", () => {
    render(
      <>
        <Row {...SHARE} />
        <Row {...AMOUNT} />
      </>,
    );

    expect(shareButton().getAttribute("aria-controls")).not.toBe(amountButton().getAttribute("aria-controls"));
  });

  it("the button's name does not change with its state", () => {
    render(<Row {...SHARE} />);
    expect(screen.getByRole("button", { name: SHARE.label })).toBeInTheDocument();

    fireEvent.click(shareButton());

    expect(screen.getByRole("button", { name: SHARE.label })).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("two buttons carry the two names they were given", () => {
    render(
      <>
        <Row {...SHARE} />
        <Row {...AMOUNT} />
      </>,
    );

    expect(shareButton()).not.toBe(amountButton());
  });

  it("the button is never disabled", () => {
    render(<Row {...SHARE} />);
    expect(shareButton()).toBeEnabled();

    fireEvent.click(shareButton());

    expect(shareButton()).toBeEnabled();
  });

  it("the box is 44 by 44 px by class and the glyph is an aria-hidden SVG with no style attribute", () => {
    render(<Row {...SHARE} />);
    const button = shareButton();

    expect(button.className).toMatch(/(^|\s)size-11(\s|$)/);
    const glyph = button.querySelector("svg");
    expect(glyph).not.toBeNull();
    expect(glyph).toHaveAttribute("aria-hidden", "true");
    expect(button.querySelector("[style]")).toBeNull();
    expect(button).not.toHaveAttribute("style");
    expect(button.textContent).toBe("");
  });

  it("the glyph takes its colour from a text class: ink-3 at rest, ink while open", () => {
    render(<Row {...SHARE} />);
    expect(shareButton().className).toMatch(/(^|\s)text-ink-3(\s|$)/);

    fireEvent.click(shareButton());

    expect(shareButton().className).toMatch(/(^|\s)text-ink(\s|$)/);
    expect(shareButton().className).not.toMatch(/(^|\s)text-ink-3(\s|$)/);
  });
});
