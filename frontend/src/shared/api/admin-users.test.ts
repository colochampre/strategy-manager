import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchAdminUsers } from "@/shared/api/admin-users";
import { adminUser, jsonResponse, stubApi, unlock } from "@/test/harness";

function serve(body: unknown) {
  return stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) =>
    url.endsWith("/api/admin/users") ? Promise.resolve(jsonResponse(body)) : undefined,
  );
}

beforeEach(() => {
  unlock();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GET /api/admin/users", () => {
  it("answers the list as the server wrote it", async () => {
    serve([adminUser({ display_name: null }), adminUser({ email: "b@example.com" })]);

    const users = await fetchAdminUsers();

    expect(users).toHaveLength(2);
    expect(users[0]).toMatchObject({ email: "ana@example.com", display_name: null, mode: "LIVE", open_positions: 2 });
    expect(users[1]?.email).toBe("b@example.com");
  });

  it("answers an empty list as an empty list", async () => {
    serve([]);

    await expect(fetchAdminUsers()).resolves.toEqual([]);
  });

  it.each([
    ["not a list", { users: [] }],
    ["an entry that is not a user", [1]],
    ["an entry that is a list", [[]]],
    ["no e-mail", [adminUser({ email: undefined })]],
    ["an e-mail that is not text", [adminUser({ email: 1 })]],
    ["a name that is missing", [adminUser({ display_name: undefined })]],
    ["a name that is not text", [adminUser({ display_name: 1 })]],
    ["an unknown mode", [adminUser({ mode: "PAPER" })]],
    ["a key list that is no list", [adminUser({ exchanges_with_key: "bybit" })]],
    ["a key list of numbers", [adminUser({ exchanges_with_key: [1] })]],
    ["a no-key list that is no list", [adminUser({ exchanges_with_no_key: null })]],
    ["a no-key list of numbers", [adminUser({ exchanges_with_no_key: [1] })]],
    ["a negative subscription count", [adminUser({ subscriptions: -1 })]],
    ["a fractional subscription count", [adminUser({ subscriptions: 1.5 })]],
    ["a position count that is text", [adminUser({ open_positions: "2" })]],
    ["no last sign-in", [adminUser({ last_seen_at: null })]],
  ])("refuses %s", async (_name, body) => {
    serve(body);

    await expect(fetchAdminUsers()).rejects.toThrow("Unexpected response shape");
  });
});
