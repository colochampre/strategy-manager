import { useSyncExternalStore } from "react";

/** Tailwind's `lg`: the width at which the shell swaps its bottom bar for the side rail. */
const WIDE_QUERY = "(min-width: 1024px)";

function subscribe(onChange: () => void): () => void {
  if (typeof globalThis.matchMedia !== "function") return () => undefined;
  const list = globalThis.matchMedia(WIDE_QUERY);
  list.addEventListener("change", onChange);
  return () => list.removeEventListener("change", onChange);
}

/** A browser without `matchMedia` (and jsdom) reads as wide, the layout with the fewest moving parts. */
function getSnapshot(): boolean {
  return typeof globalThis.matchMedia === "function" ? globalThis.matchMedia(WIDE_QUERY).matches : true;
}

/**
 * Whether the viewport is at least `lg` wide. The Overview uses it to render
 * the decision rail in exactly ONE place: CSS alone would need the rail twice
 * (one copy hidden), which doubles the dialogs and the accessible landmarks.
 */
export function useIsWide(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, () => true);
}
