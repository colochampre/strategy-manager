import { render } from "@testing-library/react";
import { createElement, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { pressRangeKey, pressTab } from "@/test/keyboard";

// `pressRangeKey` stands for the browser's default action on a focused range input, as `pressEnter`
// stands for a button's. What a test proves with it is the markup's side: a real, enabled range input
// with the right `min`, `max` and `step`, and no handler that swallows the key.

interface RangeOptions {
  min?: string;
  max?: string;
  step?: string;
  value?: string;
  disabled?: boolean;
}

function mountRange({ min = "1", max = "100", step = "1", value = "34", disabled = false }: RangeOptions = {}) {
  const input = document.createElement("input");
  input.type = "range";
  input.min = min;
  input.max = max;
  input.step = step;
  input.value = value;
  input.disabled = disabled;
  document.body.append(input);
  if (!disabled) input.focus();
  return input;
}

afterEach(() => {
  document.body.replaceChildren();
});

describe("pressRangeKey", () => {
  it.each([
    ["ArrowRight", "35"],
    ["ArrowUp", "35"],
    ["ArrowLeft", "33"],
    ["ArrowDown", "33"],
  ])("an arrow adds or removes one step: %s from 34 gives %s", (key, expected) => {
    const input = mountRange();

    pressRangeKey(key);

    expect(input.value).toBe(expected);
  });

  it("adds the step the input declares", () => {
    const input = mountRange({ min: "0", max: "100", step: "5", value: "10" });

    pressRangeKey("ArrowRight");
    expect(input.value).toBe("15");
    pressRangeKey("ArrowLeft");
    pressRangeKey("ArrowLeft");

    expect(input.value).toBe("5");
  });

  it("Home sets min and End sets max", () => {
    const input = mountRange({ min: "1", max: "100", value: "34" });

    pressRangeKey("End");
    expect(input.value).toBe("100");
    pressRangeKey("Home");

    expect(input.value).toBe("1");
  });

  it("the result is clamped to min and max", () => {
    const input = mountRange({ min: "1", max: "100", value: "99" });

    pressRangeKey("ArrowRight");
    pressRangeKey("ArrowRight");
    expect(input.value).toBe("100");

    input.value = "2";
    pressRangeKey("ArrowLeft");
    pressRangeKey("ArrowLeft");
    expect(input.value).toBe("1");
  });

  it("clamps a step that would pass the end", () => {
    const input = mountRange({ min: "0", max: "100", step: "5", value: "98" });

    pressRangeKey("ArrowRight");

    expect(input.value).toBe("100");
  });

  it("fires the input and change events, once each, input first", () => {
    const input = mountRange();
    const seen: string[] = [];
    input.addEventListener("input", () => seen.push("input"));
    input.addEventListener("change", () => seen.push("change"));

    pressRangeKey("ArrowRight");

    expect(input.value).toBe("35");
    expect(seen).toEqual(["input", "change"]);
  });

  it("reaches a React onChange with the new value", () => {
    const changes: string[] = [];
    function Controlled() {
      const [value, setValue] = useState("34");
      return createElement("input", {
        type: "range",
        min: 1,
        max: 100,
        step: 1,
        value,
        onChange: (event: { target: { value: string } }) => {
          changes.push(event.target.value);
          setValue(event.target.value);
        },
      });
    }
    const { container } = render(createElement(Controlled));
    const input = container.querySelector("input") as HTMLInputElement;
    input.focus();

    pressRangeKey("ArrowRight");

    expect(changes).toEqual(["35"]);
    expect(input.value).toBe("35");
  });

  it("does nothing when the keydown was prevented", () => {
    const input = mountRange();
    const events: string[] = [];
    input.addEventListener("keydown", (event) => event.preventDefault());
    input.addEventListener("input", () => events.push("input"));
    input.addEventListener("change", () => events.push("change"));

    pressRangeKey("ArrowRight");

    expect(input.value).toBe("34");
    expect(events).toEqual([]);
  });

  it("does nothing when the input is disabled", () => {
    const input = mountRange({ disabled: true });
    const onInput = vi.fn();
    input.addEventListener("input", onInput);
    Object.defineProperty(document, "activeElement", { value: input, configurable: true });

    try {
      pressRangeKey("ArrowRight");
    } finally {
      Reflect.deleteProperty(document, "activeElement");
    }

    expect(input.value).toBe("34");
    expect(onInput).not.toHaveBeenCalled();
  });

  it("ignores a key that is not an arrow, Home or End", () => {
    const input = mountRange();
    const onInput = vi.fn();
    input.addEventListener("input", onInput);

    pressRangeKey("a");
    pressRangeKey("PageUp");

    expect(input.value).toBe("34");
    expect(onInput).not.toHaveBeenCalled();
  });

  it("does nothing when the focused element is not a range input", () => {
    const text = document.createElement("input");
    text.type = "text";
    text.value = "34";
    document.body.append(text);
    text.focus();

    pressRangeKey("ArrowRight");

    expect(text.value).toBe("34");
  });

  it("moves a range input that really is one: a real arrow press reaches its value", () => {
    const input = mountRange({ value: "50" });

    pressRangeKey("ArrowRight");
    pressRangeKey("ArrowRight");
    pressRangeKey("ArrowLeft");

    expect(input.value).toBe("51");
  });
});

// `pressTab` stands for sequential focus navigation, which jsdom lacks. A real Tab skips an element whose
// tabindex is -1, whatever its tag, so the helper must too: a test of the tab order that cannot see a
// `tabIndex={-1}` put on a button would pass for the wrong reason.

describe("pressTab", () => {
  function mountButtons(...tabIndexes: Array<string | null>) {
    return tabIndexes.map((tabIndex) => {
      const button = document.createElement("button");
      if (tabIndex !== null) button.setAttribute("tabindex", tabIndex);
      document.body.append(button);
      return button;
    });
  }

  it("moves to the next tabbable element in document order, and wraps", () => {
    const [first, second] = mountButtons(null, null);

    expect(pressTab()).toBe(first);
    expect(pressTab()).toBe(second);
    expect(pressTab()).toBe(first);
  });

  it("skips a button whose tabindex is -1", () => {
    const [first, skipped, third] = mountButtons(null, "-1", null);

    expect(pressTab()).toBe(first);
    expect(pressTab()).toBe(third);
    expect(pressTab()).not.toBe(skipped);
  });

  it("does not skip a button whose tabindex is 0", () => {
    const [first, second] = mountButtons(null, "0");

    expect(pressTab()).toBe(first);
    expect(pressTab()).toBe(second);
  });

  it("skips a disabled button", () => {
    const [first, disabled, third] = mountButtons(null, null, null);
    disabled?.setAttribute("disabled", "");

    expect(pressTab()).toBe(first);
    expect(pressTab()).toBe(third);
  });
});
