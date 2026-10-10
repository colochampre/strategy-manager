import { fireEvent } from "@testing-library/react";

/**
 * A minimal keyboard for jsdom, which implements neither sequential focus navigation nor the
 * activation of a button by Enter or Space. `@testing-library/user-event` is not a dependency of
 * the project, so these two helpers stand for the browser's default actions: Tab focuses the next
 * tabbable element in document order, and Enter or Space on a button activates it. What a test
 * proves with them is the markup's side of the contract: a real, enabled, focusable `<button>`.
 */
const TABBABLE = 'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function tabbables(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>(TABBABLE)].filter(
    (element) => element.closest("[inert]") === null && element.getAttribute("tabindex") !== "-1",
  );
}

/** Moves focus to the next tabbable element after the focused one (the first when none is focused). */
export function pressTab(): HTMLElement | undefined {
  const all = tabbables();
  const index = all.indexOf(document.activeElement as HTMLElement);
  const target = all[index + 1] ?? all[0];
  target?.focus();
  return target;
}

/** Presses Enter on the focused element: a button fires its click on keydown. */
export function pressEnter(): void {
  const target = document.activeElement as HTMLElement | null;
  if (target === null) return;
  const proceeded = fireEvent.keyDown(target, { key: "Enter" });
  if (proceeded && target.tagName === "BUTTON") fireEvent.click(target);
}

/** The number an attribute holds, or the browser's default for a range input when it is absent. */
function rangeAttribute(value: string, fallback: number): number {
  return value === "" ? fallback : Number(value);
}

/** Where a key moves a range input, or `null` for a key the input does nothing with. */
function rangeTarget(key: string, current: number, min: number, max: number, step: number): number | null {
  if (key === "ArrowRight" || key === "ArrowUp") return current + step;
  if (key === "ArrowLeft" || key === "ArrowDown") return current - step;
  if (key === "Home") return min;
  if (key === "End") return max;
  return null;
}

/**
 * Presses a key on the focused range input: an arrow adds or removes one `step`, Home sets `min` and End
 * sets `max`, and the result is clamped. Nothing happens when the keydown was prevented, when the input is
 * disabled, or when the focused element is not a range input. It then fires the `input` and `change`
 * events, so a React `onChange` sees the new value. Page Up and Page Down are not modelled: their step is
 * the browser's.
 */
export function pressRangeKey(key: string): void {
  const target = document.activeElement;
  if (!(target instanceof HTMLInputElement) || target.type !== "range" || target.disabled) return;
  const proceeded = fireEvent.keyDown(target, { key });
  if (!proceeded) return;
  const min = rangeAttribute(target.min, 0);
  const max = rangeAttribute(target.max, 100);
  const step = rangeAttribute(target.step, 1);
  const moved = rangeTarget(key, Number(target.value), min, max, step);
  if (moved === null) return;
  fireEvent.input(target, { target: { value: String(Math.min(max, Math.max(min, moved))) } });
  fireEvent.change(target);
}

/** Presses Space on the focused element: a button fires its click on keyup. */
export function pressSpace(): void {
  const target = document.activeElement as HTMLElement | null;
  if (target === null) return;
  const proceeded = fireEvent.keyDown(target, { key: " " });
  fireEvent.keyUp(target, { key: " " });
  if (proceeded && target.tagName === "BUTTON") fireEvent.click(target);
}
