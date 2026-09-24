/**
 * Wraps a `Storage` (normally `window.localStorage`) so that a throwing or
 * unavailable storage — private browsing mode is the common case — never
 * crashes the caller. The first failed operation degrades the wrapper to an
 * in-memory `Map` for the rest of the session; it does not re-probe the real
 * storage on every call, so a temporarily-blocked write does not flip back
 * and forth.
 */

interface SyncStorage {
  getItem(name: string): string | null;
  setItem(name: string, value: string): void;
  removeItem(name: string): void;
}

export function createSafeStorage(getStorage: () => Storage = () => window.localStorage): SyncStorage {
  const memory = new Map<string, string>();
  let degraded = false;

  return {
    getItem(name) {
      if (degraded) {
        return memory.get(name) ?? null;
      }
      try {
        return getStorage().getItem(name);
      } catch {
        degraded = true;
        return memory.get(name) ?? null;
      }
    },
    setItem(name, value) {
      if (degraded) {
        memory.set(name, value);
        return;
      }
      try {
        getStorage().setItem(name, value);
      } catch {
        degraded = true;
        memory.set(name, value);
      }
    },
    removeItem(name) {
      if (degraded) {
        memory.delete(name);
        return;
      }
      try {
        getStorage().removeItem(name);
      } catch {
        degraded = true;
        memory.delete(name);
      }
    },
  };
}
