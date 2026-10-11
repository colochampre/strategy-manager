import type { CredentialEntry } from "@/shared/api/credentials";

/**
 * The four states an exchange's key can be in (design § B). `served` is a second
 * axis, not a state: it decides only whether the card has buttons.
 *
 * This module decides and holds no React and no text. The Settings card and the
 * exchange tab both call it with the same inputs, so they cannot disagree.
 */
export type KeyState = "key" | "readOnly" | "degraded" | "empty";

/** The word a state is marked with, and whether it asks the owner to act (amber) or only informs. */
export interface KeyMarkSpec {
  word: "readOnly" | "noKey";
  tone: "amber" | "neutral";
}

/** Whatever carries an exchange id: a pool, or a row of `GET /credentials`. */
interface HasExchange {
  exchange: string;
}

interface HasPoolFlag extends HasExchange {
  enabled: boolean;
}

function byName(a: string, b: string): number {
  if (a < b) return -1;
  return a > b ? 1 : 0;
}

/**
 * The exchanges the page draws, without repeats: the served ones in the file's
 * order, then every other exchange of the credentials, then every other exchange
 * that only has a pool. The last two groups are each sorted by name. So every
 * tab has a card, a stored key is always shown, and an exchange in neither route
 * (Binance before its first key) is still there.
 */
export function exchangeList(
  served: readonly string[],
  entries: readonly HasExchange[],
  pools: readonly HasExchange[],
): string[] {
  const listed = new Set(served);
  const others = (rows: readonly HasExchange[]): string[] => {
    const names = [...new Set(rows.map((row) => row.exchange))].filter((name) => !listed.has(name)).sort(byName);
    for (const name of names) listed.add(name);
    return names;
  };
  const fromCredentials = others(entries);
  const fromPools = others(pools);
  return [...served, ...fromCredentials, ...fromPools];
}

/**
 * Whether the exchange has at least one enabled pool (the worker's DEGRADED rule
 * is per exchange, not per known pool). `undefined` is a pools read that has no
 * answer yet or failed, and that is unknown, never "no pool on": an exchange must
 * not be called degraded, or quiet, on a guess.
 */
export function poolOn(exchange: string, pools: readonly HasPoolFlag[] | undefined): boolean | null {
  if (pools === undefined) return null;
  return pools.some((pool) => pool.exchange === exchange && pool.enabled);
}

/** The part of a query's result that decides whether its data may be believed. */
interface ReadResult<T> {
  status: string;
  data: T | undefined;
}

/**
 * The pools the card and the tab may rely on. STUB (task 13.5.1-style RED stub):
 * answers wrongly on purpose, so the test written next fails on its assertion.
 */
export function knownPools<T>(query: ReadResult<T>): T | undefined {
  return query.data;
}

/**
 * The state of one exchange. `entry` is its row of `GET /credentials`, or
 * `undefined` when it is not listed; an `EMPTY` row and a missing row mean the
 * same thing, no active key. `poolOn` unknown is read as quiet: an exchange
 * without a key is only called degraded when a pool is KNOWN to be on.
 */
export function keyState(entry: CredentialEntry | undefined, poolOn: boolean | null): KeyState {
  if (entry?.status === "STORED") return entry.trade_capable ? "key" : "readOnly";
  return poolOn === true ? "degraded" : "empty";
}

/** The mark of a state, or none: a key that trades says nothing. */
export function keyMark(state: KeyState): KeyMarkSpec | null {
  switch (state) {
    case "readOnly":
      return { word: "readOnly", tone: "amber" };
    case "degraded":
      return { word: "noKey", tone: "amber" };
    case "empty":
      return { word: "noKey", tone: "neutral" };
    case "key":
      return null;
  }
}
