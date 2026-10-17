import { useEffect } from "react";
import { useLocation } from "react-router";

/** The id a location's hash names, or `null` for no hash or one that is not a valid encoding. */
function idOf(hash: string): string | null {
  if (hash.length <= 1) return null;
  try {
    return decodeURIComponent(hash.slice(1));
  } catch {
    return null;
  }
}

/**
 * Brings the element the location's hash names into view. The router does nothing with a hash, so a link to
 * `#discrepancy-<id>` would seem to lead nowhere, most of all on a phone where the item sits far down the page.
 * It scrolls once the page is mounted, and again whenever the hash changes while the page is on screen; a
 * re-render at the same hash leaves the scroll position to the owner.
 *
 * `ready` says the element can exist: a page that draws its items only after a read passes `false` until the
 * read has answered, so the hash is not looked for before the item is drawn. The scroll then happens the moment
 * `ready` turns true. A hash naming no element does nothing.
 */
export function useHashScroll(ready: boolean = true): void {
  const { hash } = useLocation();

  useEffect(() => {
    if (!ready) return;
    const id = idOf(hash);
    if (id === null) return;
    document.getElementById(id)?.scrollIntoView();
  }, [hash, ready]);
}
