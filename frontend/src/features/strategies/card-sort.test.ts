import { describe, expect, it } from "vitest";

import { DEFAULT_SORT, nextSort, sortCards } from "@/features/strategies/card-sort";
import type { CardSort } from "@/features/strategies/card-sort";

interface Item {
  name: string;
  value: number | null;
}

const read = (item: Item): number | null => item.value;
const names = (items: readonly Item[]) => items.map((item) => item.name);

const ITEMS: Item[] = [
  { name: "a", value: 2 },
  { name: "b", value: null },
  { name: "c", value: 9 },
  { name: "d", value: 5 },
];

describe("the default sort", () => {
  it("is the return, descending", () => {
    expect(DEFAULT_SORT).toEqual({ key: "return", direction: "desc" });
  });
});

describe("choosing a key", () => {
  it("sorts a key that is not active descending", () => {
    expect(nextSort({ key: "return", direction: "asc" }, "age")).toEqual({ key: "age", direction: "desc" });
  });

  it("flips the active key from descending to ascending", () => {
    expect(nextSort({ key: "capital", direction: "desc" }, "capital")).toEqual({ key: "capital", direction: "asc" });
  });

  it("flips the active key back from ascending to descending", () => {
    expect(nextSort({ key: "capital", direction: "asc" }, "capital")).toEqual({ key: "capital", direction: "desc" });
  });
});

describe("sorting cards", () => {
  const desc: CardSort = { key: "return", direction: "desc" };
  const asc: CardSort = { key: "return", direction: "asc" };

  it("puts the largest first when descending", () => {
    expect(names(sortCards(ITEMS, desc, read))).toEqual(["c", "d", "a", "b"]);
  });

  it("puts the smallest first when ascending", () => {
    expect(names(sortCards(ITEMS, asc, read))).toEqual(["a", "d", "c", "b"]);
  });

  it("puts a card with no figure last in both directions", () => {
    expect(names(sortCards(ITEMS, desc, read)).at(-1)).toBe("b");
    expect(names(sortCards(ITEMS, asc, read)).at(-1)).toBe("b");
  });

  it("keeps the list's own order among equal figures and among cards with none", () => {
    const tied: Item[] = [
      { name: "x", value: null },
      { name: "y", value: 1 },
      { name: "z", value: null },
      { name: "w", value: 1 },
    ];
    expect(names(sortCards(tied, desc, read))).toEqual(["y", "w", "x", "z"]);
    expect(names(sortCards(tied, asc, read))).toEqual(["y", "w", "x", "z"]);
  });

  it("leaves the list it was given as it was", () => {
    const before = names(ITEMS);
    sortCards(ITEMS, desc, read);
    expect(names(ITEMS)).toEqual(before);
  });

  it("hands the key to the reader of the figure", () => {
    const keys: string[] = [];
    sortCards(ITEMS, { key: "trades", direction: "desc" }, (_item, key) => {
      keys.push(key);
      return 1;
    });
    expect(new Set(keys)).toEqual(new Set(["trades"]));
  });
});
