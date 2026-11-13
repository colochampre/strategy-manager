import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LeverageSlider } from "@/features/strategies/LeverageSlider";
import type { LeverageSliderProps } from "@/features/strategies/LeverageSlider";
import { RANGE_CLASS } from "@/features/strategies/ShareSlider";
import { leveragePosition } from "@/features/strategies/leverage-value";
import { pressEnter, pressRangeKey } from "@/test/keyboard";

// Presentational, like ShareSlider: it takes the text, the handle and its callbacks, and holds nothing.

function props(overrides: Partial<LeverageSliderProps> = {}): LeverageSliderProps {
  return {
    fieldId: "lev-field",
    labelId: "lev-label",
    text: "5",
    handle: 5,
    value: 5,
    disabled: false,
    invalid: false,
    onText: vi.fn(),
    onHandle: vi.fn(),
    onStop: vi.fn(),
    ...overrides,
  };
}

function renderSlider(overrides: Partial<LeverageSliderProps> = {}) {
  const given = props(overrides);
  const view = render(
    <div>
      <label id={given.labelId} htmlFor={given.fieldId}>
        Leverage
      </label>
      {given.describedBy === undefined ? null : <p id={given.describedBy}>Enter a whole number from 1 to 20.</p>}
      <LeverageSlider {...given} />
    </div>,
  );
  return { given, view };
}

const field = () => screen.getByRole("textbox") as HTMLInputElement;
const track = () => screen.getByRole("slider", { name: "Leverage" }) as HTMLInputElement;
const stopButton = (stop: number) => screen.getByRole("button", { name: `Set the leverage to x${stop}` });
const STOPS = [5, 10, 15, 20];

function wrapper(): HTMLElement {
  const parent = field().parentElement;
  if (parent === null) throw new Error("the field has no wrapper");
  return parent;
}

describe("LeverageSlider, the field", () => {
  it("is a numeric text input named by the visible label, holding the text as typed", () => {
    renderSlider({ text: "12" });

    expect(screen.getByRole("textbox", { name: "Leverage" })).toBe(field());
    expect(field()).toHaveAttribute("type", "text");
    expect(field()).toHaveAttribute("inputmode", "numeric");
    expect(field()).toHaveAttribute("maxlength", "4");
    expect(field().value).toBe("12");
    expect(field().getAttribute("size")).toBe("2");
  });

  it("shows the x sign before the number, outside the value and hidden from assistive technology", () => {
    renderSlider();

    const sign = field().previousElementSibling;
    expect(sign).toHaveTextContent("x");
    expect(sign).toHaveAttribute("aria-hidden", "true");
    expect(field().value).toBe("5");
  });

  it("the wrapper has the look of a field", () => {
    renderSlider();

    for (const name of ["min-h-11", "border", "bg-ground", "border-rule"]) expect(wrapper()).toHaveClass(name);
  });

  it("a keystroke reaches onText exactly as typed and nothing else", () => {
    const { given } = renderSlider();

    fireEvent.change(field(), { target: { value: "x15" } });

    expect(given.onText).toHaveBeenCalledExactlyOnceWith("x15");
    expect(given.onHandle).not.toHaveBeenCalled();
    expect(given.onStop).not.toHaveBeenCalled();
  });

  it("an invalid value marks the field aria-invalid, tied to its text, with the loss border", () => {
    renderSlider({ invalid: true, describedBy: "lev-why" });

    expect(field()).toHaveAttribute("aria-invalid", "true");
    expect(field()).toHaveAccessibleDescription("Enter a whole number from 1 to 20.");
    expect(wrapper()).toHaveClass("border-loss");
    expect(wrapper()).not.toHaveClass("border-rule");
  });

  it("a valid value is not marked invalid", () => {
    renderSlider();

    expect(field()).toHaveAttribute("aria-invalid", "false");
  });

  it("a disabled control disables the field, the range and the stops", () => {
    renderSlider({ disabled: true });

    expect(field()).toBeDisabled();
    expect(track()).toBeDisabled();
    for (const stop of STOPS) expect(stopButton(stop)).toBeDisabled();
  });
});

describe("LeverageSlider, the track and the stops", () => {
  it("the track is a range from 1 to 20 in steps of 1, at the handle the container gives", () => {
    renderSlider({ handle: 7, value: 7, text: "7" });

    expect(track()).toHaveAttribute("type", "range");
    expect(track()).toHaveAttribute("min", "1");
    expect(track()).toHaveAttribute("max", "20");
    expect(track()).toHaveAttribute("step", "1");
    expect(track().value).toBe("7");
  });

  it("its value text reads x5, and the handle's step when the text is not a value", () => {
    const { view } = renderSlider();
    expect(track()).toHaveAttribute("aria-valuetext", "x5");

    view.rerender(<LeverageSlider {...props({ handle: 9, value: null, text: "9.5" })} />);
    expect(screen.getByRole("slider")).toHaveAttribute("aria-valuetext", "x9");
  });

  it("moving the range reports the new step, by pointer and by keys", () => {
    const { given } = renderSlider({ handle: 5 });

    fireEvent.change(track(), { target: { value: "12" } });
    track().focus();
    pressRangeKey("ArrowRight");
    pressRangeKey("End");

    expect(given.onHandle).toHaveBeenNthCalledWith(1, 12);
    expect(given.onHandle).toHaveBeenNthCalledWith(2, 6);
    expect(given.onHandle).toHaveBeenNthCalledWith(3, 20);
  });

  it("the filled part and the four stops are drawn where leverage-value puts them", () => {
    const { view } = renderSlider({ handle: 10, value: 10, text: "10" });
    const svg = view.container.querySelector("svg");
    if (svg === null) throw new Error("no drawing");

    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg.querySelector("line.stroke-gain")).toHaveAttribute("x2", leveragePosition(10));
    expect([...svg.querySelectorAll("circle")].map((circle) => circle.getAttribute("cx"))).toEqual(
      STOPS.map(leveragePosition),
    );
    expect([...svg.querySelectorAll("circle")].map((circle) => circle.classList.contains("fill-gain"))).toEqual([
      true,
      true,
      false,
      false,
    ]);
  });

  it("the filled part ends at the track's own ends", () => {
    const { view } = renderSlider({ handle: 1, value: 1, text: "1" });
    expect(view.container.querySelector("svg line.stroke-gain")).toHaveAttribute("x2", "0%");

    view.rerender(<LeverageSlider {...props({ handle: 20, value: 20, text: "20" })} />);
    expect(view.container.querySelector("svg line.stroke-gain")).toHaveAttribute("x2", "100%");
  });

  it("the four stops are buttons named 'Set the leverage to x5' and so on, showing x5, x10, x15, x20", () => {
    renderSlider();

    for (const stop of STOPS) {
      expect(stopButton(stop).tagName).toBe("BUTTON");
      expect(stopButton(stop)).toHaveTextContent(`x${stop}`);
      expect(stopButton(stop)).toHaveClass("size-11");
    }
    expect(track()).toHaveClass("h-11");
  });

  it.each([
    [5, "left-[21.0526%]"],
    [10, "left-[47.3684%]"],
    [15, "left-[73.6842%]"],
    [20, "left-[100%]"],
  ])("the stop %i sits at one fixed class, the position leverage-value gives", (stop, className) => {
    renderSlider();

    expect(stopButton(stop)).toHaveClass(className);
    expect(className).toBe(`left-[${leveragePosition(stop)}]`);
  });

  it("a stop is aria-pressed exactly when the value equals it", () => {
    const { view } = renderSlider({ value: 10, handle: 10, text: "10" });
    expect(STOPS.map((stop) => stopButton(stop).getAttribute("aria-pressed"))).toEqual(["false", "true", "false", "false"]);

    view.rerender(<LeverageSlider {...props({ value: 7, handle: 7, text: "7" })} />);
    expect(STOPS.map((stop) => stopButton(stop).getAttribute("aria-pressed"))).toEqual(["false", "false", "false", "false"]);

    view.rerender(<LeverageSlider {...props({ value: null, handle: 5, text: "5x" })} />);
    expect(STOPS.map((stop) => stopButton(stop).getAttribute("aria-pressed"))).toEqual(["false", "false", "false", "false"]);
  });

  it("a press on a stop, or Enter on it, reports that stop", () => {
    const { given } = renderSlider();

    fireEvent.click(stopButton(15));
    stopButton(20).focus();
    pressEnter();

    expect(given.onStop).toHaveBeenNthCalledWith(1, 15);
    expect(given.onStop).toHaveBeenNthCalledWith(2, 20);
  });

  it("uses the share slider's range classes and carries no style attribute", () => {
    const { view } = renderSlider();

    for (const name of RANGE_CLASS.split(" ")) expect(track()).toHaveClass(name);
    expect(view.container.querySelectorAll("[style]")).toHaveLength(0);
  });
});

describe("LeverageSlider, under the cap of a stop level", () => {
  it("offers no stop above the cap and holds the handle at it", () => {
    const { given } = renderSlider({ max: 9, handle: 5, value: 5, text: "5" });

    expect(stopButton(5)).toBeEnabled();
    for (const stop of [10, 15, 20]) expect(stopButton(stop)).toBeDisabled();

    fireEvent.change(track(), { target: { value: "15" } });
    expect(given.onHandle).toHaveBeenCalledWith(9);
  });

  it("offers every stop with no cap given, as it always did", () => {
    renderSlider();

    for (const stop of STOPS) expect(stopButton(stop)).toBeEnabled();
  });
});
