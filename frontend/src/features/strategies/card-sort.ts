/** What a list of cards can be sorted by: the figures the card shows. */
export type SortKey = "age" | "trades" | "return" | "subscribers" | "capital";

export type SortDirection = "desc" | "asc";

export interface CardSort {
  key: SortKey;
  direction: SortDirection;
}

/** The keys, in the order the sort control offers them. */
export const SORT_KEYS: readonly SortKey[] = ["age", "trades", "return", "subscribers", "capital"];

/** Return, largest first: what a reader looks for first (owner, 2026-11-08). */
export const DEFAULT_SORT: CardSort = { key: "return", direction: "desc" };

/**
 * What choosing a key does: a key that is not active sorts descending; the active key again flips the direction
 * (descending to ascending and back).
 */
export function nextSort(current: CardSort, key: SortKey): CardSort {
  if (current.key !== key) return { key, direction: "desc" };
  return { key, direction: current.direction === "desc" ? "asc" : "desc" };
}

/**
 * A copy of `items` ordered by the figure `read` finds for the active key. A card with no figure (null) sorts last
 * whichever way the list runs, and equal figures keep the list's own order.
 */
export function sortCards<T>(
  items: readonly T[],
  { key, direction }: CardSort,
  read: (item: T, key: SortKey) => number | null,
): T[] {
  const sign = direction === "desc" ? -1 : 1;
  return items
    .map((item, index) => ({ item, index, figure: read(item, key) }))
    .sort((a, b) => {
      if (a.figure === null || b.figure === null) {
        if (a.figure === b.figure) return a.index - b.index;
        return a.figure === null ? 1 : -1;
      }
      const order = a.figure - b.figure;
      return order === 0 ? a.index - b.index : sign * order;
    })
    .map(({ item }) => item);
}
