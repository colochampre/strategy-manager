import { useSyncExternalStore } from "react";

/**
 * The instant a user last opened the Notifications page, kept per user in this browser (RD.5). The bell asks what
 * arrived after it. Local storage can be absent, full or refused (a private window, blocked site data), so every
 * access is guarded and a refused write is kept in memory for the life of the page instead.
 */
const PREFIX = "strategy-manager.notifications.last-opened.";

const listeners = new Set<() => void>();
/** Only what the browser refused to keep; a working storage is read first and is the single source. */
const refused = new Map<string, string>();

/**
 * The key of a user's instant. The panel's `/me` has no user id, so the user is told apart by a 32-bit FNV-1a
 * digest of their lowercased e-mail address: the address itself is never written to the browser's storage.
 */
export function storageKeyOf(user: string): string {
  let digest = 0x811c9dc5;
  for (const unit of user.toLowerCase()) {
    digest ^= unit.codePointAt(0) ?? 0;
    digest = Math.imul(digest, 0x01000193) >>> 0;
  }
  return `${PREFIX}${digest.toString(16).padStart(8, "0")}`;
}

const keyOf = storageKeyOf;

export function readLastOpened(user: string): string | null {
  try {
    const stored = window.localStorage.getItem(keyOf(user));
    if (stored !== null) return stored;
  } catch {
    // Unreadable storage: fall through to what was kept in memory.
  }
  return refused.get(keyOf(user)) ?? null;
}

/** Records `instant` (now by default) as the moment the page was opened, and tells every bell. */
export function storeLastOpened(user: string, instant: string = new Date().toISOString()): void {
  try {
    window.localStorage.setItem(keyOf(user), instant);
    refused.delete(keyOf(user));
  } catch {
    refused.set(keyOf(user), instant);
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The stored instant of `user`, null while there is none or no user yet; it follows `storeLastOpened`. */
export function useLastOpened(user: string | null): string | null {
  return useSyncExternalStore(subscribe, () => (user === null ? null : readLastOpened(user)));
}
