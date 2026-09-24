import { afterEach, beforeEach, describe, expect, expectTypeOf, it, vi } from "vitest";

import { ApiError, apiFetch } from "@/shared/api/client";
import type { BookingProposal, ProposedFill } from "@/shared/api/types";
import { useTokenStore } from "@/shared/auth/token-store";

function fakeResponse(body: unknown, status: number, ok: boolean = status >= 200 && status < 300): Response {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
  } as Response;
}

describe("apiFetch", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useTokenStore.setState({ token: null });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the stored token as a Bearer Authorization header", async () => {
    useTokenStore.getState().setToken("secret-token");
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ ok: true }, 200));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/reconciliation/bookings");

    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(call[1].headers);
    expect(headers.get("Authorization")).toBe("Bearer secret-token");
  });

  it("clears the token store on any 401 response, so TokenGate re-renders", async () => {
    useTokenStore.getState().setToken("stale-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(fakeResponse({ detail: "Not authenticated" }, 401, false));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiFetch("/reconciliation/bookings")).rejects.toBeInstanceOf(ApiError);

    expect(useTokenStore.getState().token).toBeNull();
  });

  it.each([
    [409, { outcome: "SUPERSEDED", detail: "the observation moved" }],
    [503, { outcome: "DRY_RUN_REFUSED", detail: "dry run" }],
    [422, { outcome: "REASON_REQUIRED", detail: "a reason is required" }],
  ] as const)("throws a typed ApiError carrying outcome and detail on a %i refusal", async (status, body) => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse(body, status, false));
    vi.stubGlobal("fetch", fetchMock);

    const error = (await apiFetch("/reconciliation/bookings/id/approve", { method: "POST" }).catch(
      (caught: unknown) => caught,
    )) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(status);
    expect(error.outcome).toBe(body.outcome);
    expect(error.detail).toBe(body.detail);
  });

  it("throws a typed ApiError for a plain FastAPI 404 body, never a resolved value", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(fakeResponse({ detail: "no such booking proposal" }, 404, false));
    vi.stubGlobal("fetch", fetchMock);

    const error = (await apiFetch("/reconciliation/bookings/unknown").catch(
      (caught: unknown) => caught,
    )) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(404);
    expect(error.detail).toBe("no such booking proposal");
  });

  it("throws a typed ApiError for a 500 with a non-JSON error body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.reject(new SyntaxError("Unexpected token in JSON")),
    } as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);

    const error = (await apiFetch("/reconciliation/bookings").catch((caught: unknown) => caught)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(500);
  });

  it("never resolves a non-2xx response as success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ outcome: "SUPERSEDED", detail: "x" }, 409, false));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiFetch("/reconciliation/bookings/id/approve", { method: "POST" })).rejects.toBeInstanceOf(
      ApiError,
    );
  });

  it("throws a typed ApiError on a network failure, never undefined", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    const error = await apiFetch("/reconciliation/bookings").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).not.toBeUndefined();
  });

  it("resolves the parsed JSON body on a 2xx response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ outcome: "APPROVED" }, 200));
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiFetch<{ outcome: string }>("/reconciliation/bookings/id/approve", {
      method: "POST",
    });

    expect(result).toEqual({ outcome: "APPROVED" });
  });

  it("types every money field on the proposal shape as string, never number", () => {
    expectTypeOf<BookingProposal["quantity"]>().toEqualTypeOf<string>();
    expectTypeOf<BookingProposal["observed_venue_net_base"]>().toEqualTypeOf<string>();
    expectTypeOf<BookingProposal["observed_ledger_net_base"]>().toEqualTypeOf<string>();
    expectTypeOf<ProposedFill["quantity"]>().toEqualTypeOf<string>();
    expectTypeOf<ProposedFill["price"]>().toEqualTypeOf<string>();
    expectTypeOf<ProposedFill["fee"]>().toEqualTypeOf<string>();
  });
});
