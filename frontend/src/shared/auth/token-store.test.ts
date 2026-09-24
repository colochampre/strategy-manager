import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { beforeEach, describe, expect, it, vi } from "vitest";

import { useTokenStore } from "@/shared/auth/token-store";

const STORAGE_KEY = "sm.admin_token";

describe("token store", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useTokenStore.setState({ token: null });
  });

  it("persists the token to localStorage under the sm.admin_token key", () => {
    useTokenStore.getState().setToken("abc123");

    const raw = window.localStorage.getItem(STORAGE_KEY);
    expect(raw).not.toBeNull();
    expect(JSON.parse(raw as string).state.token).toBe("abc123");
  });

  it("starts with no token when storage is empty", () => {
    expect(useTokenStore.getState().token).toBeNull();
  });

  it("clears the persisted token", () => {
    useTokenStore.getState().setToken("abc123");
    useTokenStore.getState().clearToken();

    expect(useTokenStore.getState().token).toBeNull();
    const raw = window.localStorage.getItem(STORAGE_KEY);
    expect(raw === null || JSON.parse(raw).state.token === null).toBe(true);
  });

  it("degrades to in-memory storage for the session when localStorage throws (private mode)", () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    expect(() => useTokenStore.getState().setToken("private-mode-token")).not.toThrow();
    expect(useTokenStore.getState().token).toBe("private-mode-token");

    setItemSpy.mockRestore();
  });

  it("keeps reading a degraded token from memory once storage has failed once", () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    useTokenStore.getState().setToken("still-works");
    setItemSpy.mockRestore();

    // Storage is "available" again, but the wrapper degraded for the session
    // rather than re-probing on every call.
    expect(useTokenStore.getState().token).toBe("still-works");
  });
});

function collectSourceFiles(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir)) {
    const fullPath = join(dir, entry);
    const stat = statSync(fullPath);
    if (stat.isDirectory()) {
      files.push(...collectSourceFiles(fullPath));
      continue;
    }
    if (/\.(ts|tsx)$/.test(entry)) {
      files.push(fullPath);
    }
  }
  return files;
}

describe("admin token is never sourced from the built bundle", () => {
  it("scans the source tree (not dist) for a non-test file referencing import.meta.env with a token-ish name", () => {
    // vitest's cwd is the frontend project root while running this suite.
    const srcRoot = join(process.cwd(), "src");
    // Built at runtime so this guard's own source never contains the
    // forbidden literal itself.
    const forbiddenEnvAccess = "import.meta" + ".env";

    const offenders = collectSourceFiles(srcRoot)
      .filter((file) => !/\.test\.tsx?$/.test(file))
      .filter((file) => {
        const content = readFileSync(file, "utf-8");
        return content.includes(forbiddenEnvAccess) && /token/i.test(content);
      });

    expect(offenders).toEqual([]);
  });
});
