import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
import { fetchInviteCodes, fetchStrategy, issueInviteCode, revokeInviteCode } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";
import { jsonResponse, subscriptionOf } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const CODE_ID = "22222222-2222-4222-8222-222222222222";
const TOKEN = "Zr8kQ2vN_x1yPq3sLm4tB5wC6dE7fG8hJ9kL0mN1oP2";

function strategy(overrides: Record<string, unknown> = {}): Strategy {
  return {
    id: ID,
    name: "ETH Breakout",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    subscription: subscriptionOf(ID, "100"),
    enabled: false,
    archived_at: null,
    allowed_pairs: ["ETHUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    visibility: "PRIVATE",
    share_token: null,
    secret_last4: "x4F2",
    description: null,
    subscribers: 1,
    live_subscribers: 0,
    capital: null,
    ...overrides,
  } as Strategy;
}

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("a strategy's visibility and link token, as read", () => {
  it("reads a LINK strategy with its token", async () => {
    stubFetch(jsonResponse(strategy({ visibility: "LINK", share_token: TOKEN })));

    await expect(fetchStrategy(ID)).resolves.toMatchObject({ visibility: "LINK", share_token: TOKEN });
  });

  it.each([
    ["an unknown visibility", { visibility: "UNLISTED" }],
    ["a token that is a number", { share_token: 42 }],
  ])("reads %s as an error, never as a strategy", async (_case, overrides) => {
    stubFetch(jsonResponse(strategy(overrides)));

    await expect(fetchStrategy(ID)).rejects.toBeInstanceOf(ApiError);
  });

  it("reads a strategy with no share_token key at all as an error", async () => {
    const { share_token: _omitted, ...rest } = strategy();
    stubFetch(jsonResponse(rest));

    await expect(fetchStrategy(ID)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("the author's invitation codes", () => {
  const live = { id: CODE_ID, hint: "VRXT", expires_at: "2026-11-14T10:00:00+00:00" };

  it("reads GET /api/strategies/{id}/invite-codes", async () => {
    const fetchMock = stubFetch(jsonResponse([live]));

    await expect(fetchInviteCodes(ID)).resolves.toEqual([live]);

    expect((fetchMock.mock.calls[0] as [string])[0]).toBe(`${API_BASE_URL}/api/strategies/${ID}/invite-codes`);
  });

  it.each([
    ["a body that is not a list", { codes: [live] }],
    ["a row with no expiry", [{ id: CODE_ID, hint: "VRXT" }]],
    ["a row whose hint is a number", [{ ...live, hint: 1234 }]],
    ["a row with no id", [{ hint: "VRXT", expires_at: live.expires_at }]],
  ])("reads %s as an error, never as a shorter list", async (_case, body) => {
    stubFetch(jsonResponse(body));

    await expect(fetchInviteCodes(ID)).rejects.toBeInstanceOf(ApiError);
  });

  it("issues a code with POST and keeps exactly what the answer carries", async () => {
    const fetchMock = stubFetch(jsonResponse({ ...live, code: "K7MP-VRXT", extra: "ignored" }, 201));

    await expect(issueInviteCode(ID)).resolves.toEqual({ ...live, code: "K7MP-VRXT" });

    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/strategies/${ID}/invite-codes`);
    expect(call[1].method).toBe("POST");
  });

  it.each([
    ["no code", live],
    ["an empty code", { ...live, code: "" }],
    ["a code that is a number", { ...live, code: 12345678 }],
    ["no expiry", { id: CODE_ID, hint: "VRXT", code: "K7MP-VRXT" }],
  ])("reads an issued answer with %s as an error that never echoes the body", async (_case, body) => {
    stubFetch(jsonResponse(body, 201));

    const error = await issueInviteCode(ID).then(
      () => null,
      (thrown: unknown) => thrown,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(String((error as ApiError).message)).not.toContain("K7MP");
  });

  it("keeps the code of a refused issue", async () => {
    stubFetch(jsonResponse({ detail: { error: "STRATEGY_NOT_PRIVATE", message: "not private" } }, 409));

    await expect(issueInviteCode(ID)).rejects.toMatchObject({ status: 409, code: "STRATEGY_NOT_PRIVATE" });
  });

  it("revokes one code with DELETE on its own path", async () => {
    const fetchMock = stubFetch(new Response(null, { status: 204 }));

    await expect(revokeInviteCode(ID, CODE_ID)).resolves.toBeUndefined();

    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/strategies/${ID}/invite-codes/${CODE_ID}`);
    expect(call[1].method).toBe("DELETE");
  });

  it("throws a revoke of a code that is no longer live as a 404", async () => {
    stubFetch(jsonResponse({ detail: "no such code" }, 404));

    await expect(revokeInviteCode(ID, CODE_ID)).rejects.toMatchObject({ status: 404 });
  });
});
