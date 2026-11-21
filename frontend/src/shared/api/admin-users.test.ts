import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchAdminUsers, setSuspension } from "@/shared/api/admin-users";
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

describe("PUT /api/admin/users/{id}/suspension", () => {
  function put(response: Response) {
    const fetchMock = vi.fn().mockResolvedValue(response);
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it.each([true, false])("sends exactly {suspended: %s} to the user's id", async (suspended) => {
    const fetchMock = put(jsonResponse(null, 204));

    await expect(setSuspension("u-1", suspended)).resolves.toEqual({ kind: "changed" });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/admin\/users\/u-1\/suspension$/);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toEqual({ suspended });
  });

  it.each([
    [409, { error: "CANNOT_SUSPEND_YOURSELF" }, { kind: "yourself" }],
    [404, { error: "USER_NOT_FOUND" }, { kind: "notFound" }],
    [409, { error: "ACCOUNT_CHANGED" }, { kind: "accountChanged" }],
    [403, "forbidden", { kind: "unknown" }],
    [500, "boom", { kind: "unknown" }],
    [409, { error: "SOMETHING_ELSE" }, { kind: "unknown" }],
  ])("maps a %s refusal to its result", async (status, detail, expected) => {
    put(jsonResponse({ detail }, status));

    await expect(setSuspension("u-1", true)).resolves.toEqual(expected);
  });
});

describe("GET /api/admin/users", () => {
  it("answers the list as the server wrote it", async () => {
    serve([adminUser({ display_name: null }), adminUser({ email: "b@example.com" })]);

    const users = await fetchAdminUsers();

    expect(users).toHaveLength(2);
    expect(users[0]).toMatchObject({ email: "ana@example.com", display_name: null, mode: "LIVE", open_positions: 2 });
    expect(users[1]?.email).toBe("b@example.com");
  });

  it("answers the identity the user gave, and none before they signed up", async () => {
    serve([adminUser(), adminUser({ email: "b@example.com", identity: null })]);

    const users = await fetchAdminUsers();

    expect(users[0]?.identity).toEqual({
      first_name: "Ana María",
      last_name: "Pérez",
      cuit: "20123456786",
      country: "AR",
    });
    expect(users[1]?.identity).toBeNull();
  });

  it("answers the id and when the user was suspended, or null", async () => {
    serve([adminUser({ suspended_at: "2026-11-20T10:00:00Z" }), adminUser({ email: "b@example.com" })]);

    const users = await fetchAdminUsers();

    expect(users[0]).toMatchObject({ id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", suspended_at: "2026-11-20T10:00:00Z" });
    expect(users[1]?.suspended_at).toBeNull();
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
    ["no id", [adminUser({ id: undefined })]],
    ["an id that is not text", [adminUser({ id: 1 })]],
    ["no suspension field", [adminUser({ suspended_at: undefined })]],
    ["a suspension that is not text", [adminUser({ suspended_at: true })]],
    ["no identity field", [adminUser({ identity: undefined })]],
    ["an identity that is a list", [adminUser({ identity: [] })]],
    ["an identity with no CUIT", [adminUser({ identity: { first_name: "Ana", last_name: "Pérez", country: "AR" } })]],
    [
      "an identity with a CUIT that is a number",
      [adminUser({ identity: { first_name: "Ana", last_name: "Pérez", cuit: 20123456786, country: "AR" } })],
    ],
    [
      "an identity with no last name",
      [adminUser({ identity: { first_name: "Ana", cuit: "20123456786", country: "AR" } })],
    ],
  ])("refuses %s", async (_name, body) => {
    serve(body);

    await expect(fetchAdminUsers()).rejects.toThrow("Unexpected response shape");
  });
});
