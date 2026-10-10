import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ShareSlider } from "@/features/strategies/ShareSlider";
import type { ShareSliderProps } from "@/features/strategies/ShareSlider";
import { parseDraft } from "@/features/strategies/share-value";
import i18n from "@/shared/i18n";

// The control is presentational: it takes the text, the handle, the disabled flag and its callbacks, and
// holds nothing. These tests drive it through props and read what it draws (design § B, § K).

function props(overrides: Partial<ShareSliderProps> = {}): ShareSliderProps {
  return {
    fieldId: "share-field",
    labelId: "share-label",
    text: "33.5",
    handle: 34,
    value: "33.5",
    disabled: false,
    invalid: false,
    onText: vi.fn(),
    onHandle: vi.fn(),
    onStop: vi.fn(),
    ...overrides,
  };
}

/** The slider under the visible label that names it, the way the editor places the two. */
function renderSlider(overrides: Partial<ShareSliderProps> = {}) {
  const given = props(overrides);
  const view = render(
    <div>
      <label id={given.labelId} htmlFor={given.fieldId}>
        Share of the pool per trade
      </label>
      {given.describedBy === undefined ? null : <p id={given.describedBy}>Enter a number, for example 25 or 33.5.</p>}
      <ShareSlider {...given} />
    </div>,
  );
  return { given, view };
}

function field(): HTMLInputElement {
  return screen.getByRole("textbox") as HTMLInputElement;
}

function wrapper(): HTMLElement {
  const parent = field().parentElement;
  if (parent === null) throw new Error("the field has no wrapper");
  return parent;
}

describe("ShareSlider, step 1: the field and its value", () => {
  it("the field is a text input with inputMode decimal and maxLength 12", () => {
    renderSlider();

    expect(field()).toHaveAttribute("type", "text");
    expect(field()).toHaveAttribute("inputmode", "decimal");
    expect(field()).toHaveAttribute("maxlength", "12");
  });

  it.each(["5", "33.5", "100", "123456789012"])("size is the number of characters typed: %j", (text) => {
    renderSlider({ text });

    expect(field().getAttribute("size")).toBe(String(text.length));
  });

  it("size is 1 when the field is empty", () => {
    renderSlider({ text: "" });

    expect(field().getAttribute("size")).toBe("1");
  });

  it("the input carries the field-sizing class and the one-character minimum width", () => {
    renderSlider();

    expect(field()).toHaveClass("field-sizing-content");
    expect(field()).toHaveClass("min-w-[1ch]");
  });

  it("the field is named by the visible label", () => {
    renderSlider();

    expect(screen.getByRole("textbox", { name: "Share of the pool per trade" })).toBe(field());
  });

  it("the percent sign is the input's next sibling, aria-hidden, and not part of the value", () => {
    renderSlider();

    const sign = field().nextElementSibling;
    expect(sign).not.toBeNull();
    expect(sign).toHaveTextContent("%");
    expect(sign).toHaveAttribute("aria-hidden", "true");
    expect(field().value).toBe("33.5");
  });

  it("the wrapper has the look of a field and the input has none of its own", () => {
    renderSlider();

    for (const name of ["min-h-11", "border", "bg-ground", "cursor-text", "focus-within:outline-2"]) {
      expect(wrapper()).toHaveClass(name);
    }
    for (const name of ["border-0", "bg-transparent", "pr-0.5", "outline-none"]) {
      expect(field()).toHaveClass(name);
    }
  });

  it("a press on the wrapper outside the input focuses the input", () => {
    renderSlider();

    fireEvent.mouseDown(screen.getByText("%"));
    expect(field()).toHaveFocus();
  });

  it("a press on the wrapper itself focuses the input", () => {
    renderSlider();

    fireEvent.mouseDown(wrapper());
    expect(field()).toHaveFocus();
  });

  it("on a disabled control a press on the wrapper does not focus the input", () => {
    renderSlider({ disabled: true });

    // A disabled input cannot take focus in any case, so the observable part is that the press is left alone.
    const left = fireEvent.mouseDown(screen.getByText("%"));
    expect(left).toBe(true);
    expect(field()).not.toHaveFocus();
    expect(field()).toBeDisabled();
  });

  it("an invalid value marks the field aria-invalid, tied to its text, and turns the border loss", () => {
    renderSlider({ invalid: true, describedBy: "share-why" });

    expect(field()).toHaveAttribute("aria-invalid", "true");
    expect(field()).toHaveAttribute("aria-describedby", "share-why");
    expect(field()).toHaveAccessibleDescription("Enter a number, for example 25 or 33.5.");
    expect(wrapper()).toHaveClass("border-loss");
    expect(wrapper()).not.toHaveClass("border-rule");
  });

  it("a valid value is not marked invalid and keeps the ordinary border", () => {
    renderSlider({ invalid: false });

    expect(field()).toHaveAttribute("aria-invalid", "false");
    expect(wrapper()).toHaveClass("border-rule");
    expect(wrapper()).not.toHaveClass("border-loss");
  });

  it.each(["en", "es"])("the text shows a dot in both languages: %s", async (language) => {
    await i18n.changeLanguage(language);
    try {
      renderSlider({ text: "33.5" });

      expect(field().value).toBe("33.5");
    } finally {
      await i18n.changeLanguage("en");
    }
  });

  it("typing a % is not a number: the field passes the text on exactly as typed", () => {
    const { given } = renderSlider({ text: "25" });

    fireEvent.change(field(), { target: { value: "25%" } });

    expect(given.onText).toHaveBeenCalledExactlyOnceWith("25%");
    expect(parseDraft("25%")).toEqual({ valid: false, refusal: "not-a-number" });
  });

  it("a keystroke reaches onText and nothing else", () => {
    const { given } = renderSlider({ text: "3" });

    fireEvent.change(field(), { target: { value: "33" } });

    expect(given.onText).toHaveBeenCalledExactlyOnceWith("33");
    expect(given.onHandle).not.toHaveBeenCalled();
    expect(given.onStop).not.toHaveBeenCalled();
  });

  it("no element carries a style attribute", () => {
    const { view } = renderSlider({ invalid: true, describedBy: "share-why" });

    expect(view.container.querySelectorAll("[style]")).toHaveLength(0);
  });
});
