import { useSyncExternalStore } from "react";

/** Tailwind's `lg`: the width at which the shell swaps its bottom bar for the side rail. */
const WIDE_QUERY = "(min-width: 1024px)";

/** One stable `subscribe` per query: a new function each render would resubscribe each render. */
const subscribers = new Map<string, (onChange: () => void) => () => void>();

function subscriberFor(query: string): (onChange: () => void) => () => void {
  const known = subscribers.get(query);
  if (known !== undefined) return known;
  const subscribe = (onChange: () => void): (() => void) => {
    if (typeof globalThis.matchMedia !== "function") return () => undefined;
    const list = globalThis.matchMedia(query);
    list.addEventListener("change", onChange);
    return () => list.removeEventListener("change", onChange);
  };
  subscribers.set(query, subscribe);
  return subscribe;
}

/** A browser without `matchMedia` (and jsdom) reads as wide, the layout with the fewest moving parts. */
function snapshotOf(query: string): boolean {
  return typeof globalThis.matchMedia === "function" ? globalThis.matchMedia(query).matches : true;
}

/**
 * Whether the viewport matches `query` (at least `lg` wide by default). The
 * Overview uses it to render the decision rail in exactly ONE place: CSS alone
 * would need the rail twice (one copy hidden), which doubles the dialogs and the
 * accessible landmarks.
 */
export function useIsWide(query: string = WIDE_QUERY): boolean {
  return useSyncExternalStore(
    subscriberFor(query),
    () => snapshotOf(query),
    () => true,
  );
}
