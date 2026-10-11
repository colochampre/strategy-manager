import type { CredentialEntry } from "@/shared/api/credentials";

/**
 * The four states an exchange's key can be in (design § B). `served` is a second
 * axis, not a state: it decides only whether the card has buttons.
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

/** STUB (RED): answers the served ids only. */
export function exchangeList(
  served: readonly string[],
  _entries: readonly HasExchange[],
  _pools: readonly HasExchange[],
): string[] {
  return [...served];
}

/** STUB (RED): answers "unknown" for everything. */
export function poolOn(_exchange: string, _pools: readonly HasPoolFlag[] | undefined): boolean | null {
  return null;
}

/** STUB (RED): answers "key" for everything. */
export function keyState(_entry: CredentialEntry | undefined, _poolOn: boolean | null): KeyState {
  return "key";
}

/** STUB (RED): answers no mark for everything. */
export function keyMark(_state: KeyState): KeyMarkSpec | null {
  return null;
}
