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
  return [...document.querySelectorAll<HTMLElement>(TABBABLE)].filter((element) => element.closest("[inert]") === null);
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

/** STUB (12f.10.13 RED): does nothing, until the GREEN stands for a range input's default action. */
export function pressRangeKey(_key: string): void {}

/** Presses Space on the focused element: a button fires its click on keyup. */
export function pressSpace(): void {
  const target = document.activeElement as HTMLElement | null;
  if (target === null) return;
  const proceeded = fireEvent.keyDown(target, { key: " " });
  fireEvent.keyUp(target, { key: " " });
  if (proceeded && target.tagName === "BUTTON") fireEvent.click(target);
}
