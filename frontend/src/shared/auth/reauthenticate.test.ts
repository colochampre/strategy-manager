import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { page, REAUTH_STORAGE_KEY, REAUTH_WINDOW_MS, reauthenticate } from "@/shared/auth/reauthenticate";

const T0 = 1_800_000_000_000;

describe("reauthenticate", () => {
  let reload: ReturnType<typeof vi.spyOn>;
  let now: number;

  beforeEach(() => {
    window.sessionStorage.clear();
    now = T0;
    reload = vi.spyOn(page, "reload").mockImplementation(() => undefined);
    vi.spyOn(page, "now").mockImplementation(() => now);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reloads the page, so Cloudflare Access signs the person in again", () => {
    expect(reauthenticate()).toBe(true);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("does not reload twice within a minute, so a 401 that survives the reload cannot loop", () => {
    reauthenticate();
    now = T0 + REAUTH_WINDOW_MS - 1;

    expect(reauthenticate()).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("reloads again once the minute has passed", () => {
    reauthenticate();
    now = T0 + REAUTH_WINDOW_MS;

    expect(reauthenticate()).toBe(true);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("does not reload when the guard cannot be stored, rather than risk a loop", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    expect(reauthenticate()).toBe(false);
    expect(reload).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem(REAUTH_STORAGE_KEY)).toBeNull();
  });
});
