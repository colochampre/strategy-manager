import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RANGE_CLASS, ShareSlider } from "@/features/strategies/ShareSlider";
import type { ShareSliderProps } from "@/features/strategies/ShareSlider";
import { handlePosition, parseDraft } from "@/features/strategies/share-value";
import i18n from "@/shared/i18n";
import { pressEnter, pressRangeKey, pressSpace, pressTab } from "@/test/keyboard";

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

const STOPS = [25, 50, 75, 100];

function track(): HTMLInputElement {
  return screen.getByRole("slider", { name: "Share of the pool per trade" }) as HTMLInputElement;
}

function stopButton(stop: number): HTMLElement {
  return screen.getByRole("button", { name: `Set the share to ${stop}%` });
}

function drawing(container: HTMLElement): SVGSVGElement {
  const svg = container.querySelector("svg");
  if (svg === null) throw new Error("the track has no drawing");
  return svg;
}

describe("ShareSlider, step 2: the track and the stops", () => {
  it("the track is a range input with min 1, max 100, step 1, named by the visible label", () => {
    renderSlider();

    expect(screen.queryByRole("slider", { name: "Share of the pool per trade" })).toBeInTheDocument();
    expect(track()).toHaveAttribute("type", "range");
    expect(track()).toHaveAttribute("min", "1");
    expect(track()).toHaveAttribute("max", "100");
    expect(track()).toHaveAttribute("step", "1");
  });

  it("the handle sits at the step the container gives", () => {
    renderSlider({ handle: 34 });

    expect(track().value).toBe("34");
  });

  it("its value text is the exact value while the handle sits at the rounded step", () => {
    renderSlider({ handle: 34, value: "33.5" });

    expect(track()).toHaveAttribute("aria-valuetext", "33.5% of the pool");
    expect(track().value).toBe("34");
  });

  it("its value text is the handle's step when the text is not a value", () => {
    renderSlider({ handle: 63, value: null, text: "62.5x" });

    expect(track()).toHaveAttribute("aria-valuetext", "63% of the pool");
  });

  it("the filled part's x2 and the four stops' cx are the positions that share-value gives", () => {
    const { view } = renderSlider({ handle: 34 });
    const svg = drawing(view.container);

    expect(svg.querySelector("line.stroke-gain")).toHaveAttribute("x2", handlePosition(34));
    expect(svg.querySelector("line.stroke-gain")).toHaveAttribute("x2", "33.3333%");
    const centres = [...svg.querySelectorAll("circle")].map((circle) => circle.getAttribute("cx"));
    expect(centres).toEqual(STOPS.map(handlePosition));
    expect(centres).toEqual(["24.2424%", "49.4949%", "74.7475%", "100%"]);
  });

  it.each([
    [1, "0%"],
    [100, "100%"],
  ])("the filled part ends at the track's own ends: handle %i", (handle, x2) => {
    const { view } = renderSlider({ handle });

    expect(drawing(view.container).querySelector("line.stroke-gain")).toHaveAttribute("x2", x2);
  });

  it("the drawing is aria-hidden and takes no press", () => {
    const { view } = renderSlider();

    expect(drawing(view.container)).toHaveAttribute("aria-hidden", "true");
    expect(drawing(view.container)).toHaveClass("pointer-events-none");
  });

  it("a stop at or below the handle takes the gain class and the others rule-strong", () => {
    const { view } = renderSlider({ handle: 50 });
    const circles = [...drawing(view.container).querySelectorAll("circle")];

    expect(circles.map((circle) => circle.classList.contains("fill-gain"))).toEqual([true, true, false, false]);
    expect(circles.map((circle) => circle.classList.contains("fill-rule-strong"))).toEqual([false, false, true, true]);
  });

  it("the four stops are buttons named 'Set the share to 25%' and so on", () => {
    renderSlider();

    for (const stop of STOPS) {
      expect(screen.queryByRole("button", { name: `Set the share to ${stop}%` })).toBeInTheDocument();
      expect(stopButton(stop)).toHaveTextContent(`${stop}%`);
      expect(stopButton(stop).tagName).toBe("BUTTON");
    }
  });

  it("a stop is aria-pressed exactly when the value equals it", () => {
    const { view } = renderSlider({ value: "75", handle: 75 });

    expect(STOPS.map((stop) => stopButton(stop).getAttribute("aria-pressed"))).toEqual(["false", "false", "true", "false"]);
    view.rerender(<ShareSlider {...props({ value: "33.5", handle: 34 })} />);
    expect(STOPS.map((stop) => stopButton(stop).getAttribute("aria-pressed"))).toEqual(["false", "false", "false", "false"]);
    view.rerender(<ShareSlider {...props({ value: null, handle: 25, text: "25x" })} />);
    expect(STOPS.map((stop) => stopButton(stop).getAttribute("aria-pressed"))).toEqual(["false", "false", "false", "false"]);
  });

  it("a press on a stop reports that stop", () => {
    const { given } = renderSlider();

    fireEvent.click(stopButton(50));

    expect(given.onStop).toHaveBeenCalledExactlyOnceWith(50);
  });

  it("Enter or Space activates a stop", () => {
    const { given } = renderSlider();

    stopButton(75).focus();
    pressEnter();
    stopButton(100).focus();
    pressSpace();

    expect(given.onStop).toHaveBeenNthCalledWith(1, 75);
    expect(given.onStop).toHaveBeenNthCalledWith(2, 100);
  });

  it("each stop is 44 by 44 px by class and the track is 44 px tall", () => {
    const { view } = renderSlider();

    for (const stop of STOPS) expect(stopButton(stop)).toHaveClass("size-11");
    expect(track()).toHaveClass("h-11");
    expect(track().parentElement).toHaveClass("h-11");
    expect(view.container.querySelectorAll("button")).toHaveLength(4);
  });

  it.each([
    [25, "left-[24.2424%]"],
    [50, "left-[49.4949%]"],
    [75, "left-[74.7475%]"],
    [100, "left-[100%]"],
  ])("the stop %i sits at one fixed class, the position share-value gives", (stop, className) => {
    renderSlider();

    expect(stopButton(stop)).toHaveClass(className);
    expect(className).toBe(`left-[${handlePosition(stop)}]`);
  });

  it("the vendor thumb classes and appearance-none are one constant", () => {
    renderSlider();

    expect(track()).toHaveClass("appearance-none");
    for (const name of RANGE_CLASS.split(" ")) expect(track()).toHaveClass(name);
    expect(RANGE_CLASS).toContain("[&::-webkit-slider-thumb]:appearance-none");
    expect(RANGE_CLASS).toContain("[&::-webkit-slider-thumb]:bg-gain");
    expect(RANGE_CLASS).toContain("[&::-moz-range-thumb]:bg-gain");
    expect(RANGE_CLASS).toContain("[&::-webkit-slider-runnable-track]:bg-transparent");
  });

  it.each([
    ["ArrowRight", 35],
    ["ArrowLeft", 33],
    ["Home", 1],
    ["End", 100],
  ])("%s moves the handle through pressRangeKey", (key, step) => {
    const { given } = renderSlider({ handle: 34 });

    track().focus();
    pressRangeKey(key);

    expect(given.onHandle).toHaveBeenCalledExactlyOnceWith(step);
    expect(given.onText).not.toHaveBeenCalled();
  });

  it("the stops and the track are in this order after the field: the track, then 25, 50, 75, 100", () => {
    renderSlider();

    field().focus();
    expect(pressTab()).toBe(track());
    expect(pressTab()).toBe(stopButton(25));
    expect(pressTab()).toBe(stopButton(50));
    expect(pressTab()).toBe(stopButton(75));
    expect(pressTab()).toBe(stopButton(100));
  });

  it.each([
    ["en", "Set the share to 25%", "33.5% of the pool"],
    ["es", "Fijar el porcentaje en 25 %", "33.5 % del pool"],
  ])("the stop names and the value text are translated: %s", async (language, stopName, valueText) => {
    await i18n.changeLanguage(language);
    try {
      renderSlider({ handle: 34, value: "33.5" });

      expect(screen.getByRole("button", { name: stopName })).toBeInTheDocument();
      expect(screen.getByRole("slider")).toHaveAttribute("aria-valuetext", valueText);
    } finally {
      await i18n.changeLanguage("en");
    }
  });

  it("the rendered tree has no style attribute", () => {
    const { view } = renderSlider({ handle: 63, value: "62.5" });

    expect(view.container.querySelectorAll("[style]")).toHaveLength(0);
  });
});
