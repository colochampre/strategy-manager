import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InfoButton, InfoText, useInfoDisclosure } from "@/features/strategies/InfoDisclosure";
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

  it("tabbing away from an open explanation leaves it open and so does a press elsewhere", () => {
    render(
      <>
        <Row {...SHARE} />
        <button type="button">Elsewhere</button>
      </>,
    );
    fireEvent.click(shareButton());
    shareButton().focus();

    pressTab();
    expect(screen.getByRole("button", { name: "Elsewhere" })).toHaveFocus();
    fireEvent.mouseDown(document.body);
    fireEvent.click(document.body);

    expect(screen.queryByText(SHARE.text)).toBeInTheDocument();
    expect(shareButton()).toHaveAttribute("aria-expanded", "true");
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
