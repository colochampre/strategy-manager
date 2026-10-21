import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { fetchMe } from "@/shared/api/me";
import { jsonResponse } from "@/test/harness";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchMe", () => {
  it("reads who is signed in from /api/me", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ email: "owner@example.com", is_admin: true, dry_run: false }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchMe()).resolves.toEqual({ email: "owner@example.com", isAdmin: true, dryRun: false });
    expect((fetchMock.mock.calls[0] as [string])[0]).toMatch(/\/api\/me$/);
  });

  it.each([
    ["no email", { is_admin: true, dry_run: true }],
    ["a non-boolean is_admin", { email: "owner@example.com", is_admin: "yes", dry_run: true }],
    ["a non-boolean dry_run", { email: "owner@example.com", is_admin: true, dry_run: null }],
  ])("refuses an answer with %s, so a malformed body never reads as admin", async (_label, body) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(body)));

    await expect(fetchMe()).rejects.toThrow();
  });

  it("surfaces a refusal as an ApiError with its status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "unavailable" }, 503)));

    await expect(fetchMe()).rejects.toMatchObject({ status: 503 });
    await expect(fetchMe()).rejects.toBeInstanceOf(ApiError);
  });
});
