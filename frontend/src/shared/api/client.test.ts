import { afterEach, beforeEach, describe, expect, expectTypeOf, it, vi } from "vitest";

import { ApiError, apiFetch } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
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

  it("prefixes every call with the API base URL and the /api prefix", async () => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ ok: true }, 200));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/reconciliation/bookings");

    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/reconciliation/bookings`);
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

  describe("a structured detail", () => {
    async function refusal(status: number, body: unknown): Promise<ApiError> {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse(body, status, false)));
      return (await apiFetch("/strategies", { method: "POST" }).catch((caught: unknown) => caught)) as ApiError;
    }

    it("reads the error code and the fields from a structured detail", async () => {
      const detail = { error: "UNKNOWN_PAIRS", message: "The exchange does not list YPF.", unknown: ["YPF", "ZZZ"] };

      const error = await refusal(422, { detail });

      expect(error.status).toBe(422);
      expect(error.code).toBe("UNKNOWN_PAIRS");
      expect(error.fields).toEqual(detail);
      expect(error.fields?.unknown).toEqual(["YPF", "ZZZ"]);
    });

    it("reads the code of a different structured refusal the same way", async () => {
      const error = await refusal(502, {
        detail: { error: "PAIR_CATALOGUE_UNAVAILABLE", message: "the venue did not answer" },
      });

      expect(error.code).toBe("PAIR_CATALOGUE_UNAVAILABLE");
      expect(error.fields).toEqual({ error: "PAIR_CATALOGUE_UNAVAILABLE", message: "the venue did not answer" });
    });

    it("uses the structured detail's message and never renders [object Object]", async () => {
      const error = await refusal(409, {
        detail: { error: "PAIRS_CHANGED", message: "The pairs changed while you were editing." },
      });

      expect(error.message).toBe("The pairs changed while you were editing.");
      expect(error.detail).toBe("The pairs changed while you were editing.");
      expect(error.message).not.toContain("[object Object]");
    });

    it("falls back to the status text when a structured detail carries no message", async () => {
      const error = await refusal(502, { detail: { error: "PAIR_CATALOGUE_UNAVAILABLE" } });

      expect(error.message).toBe("Request failed with status 502");
      expect(error.detail).toBeUndefined();
      expect(error.code).toBe("PAIR_CATALOGUE_UNAVAILABLE");
    });

    it("keeps a string detail and an outcome exactly as before", async () => {
      const withOutcome = await refusal(409, { outcome: "SUPERSEDED", detail: "the observation moved" });
      const plain = await refusal(404, { detail: "no such pool" });

      expect(withOutcome.outcome).toBe("SUPERSEDED");
      expect(withOutcome.detail).toBe("the observation moved");
      expect(withOutcome.message).toBe("the observation moved");
      expect(withOutcome.code).toBe("SUPERSEDED");
      expect(withOutcome.fields).toBeUndefined();
      expect(plain.detail).toBe("no such pool");
      expect(plain.message).toBe("no such pool");
      expect(plain.outcome).toBeUndefined();
      expect(plain.code).toBeUndefined();
      expect(plain.fields).toBeUndefined();
    });

    it("ignores a detail that is neither a string nor an object, and a non-string error", async () => {
      const list = await refusal(422, { detail: [{ loc: ["body"], msg: "field required" }] });
      const oddCode = await refusal(422, { detail: { error: 7, message: "x" } });

      expect(list.message).toBe("Request failed with status 422");
      expect(list.detail).toBeUndefined();
      expect(list.code).toBeUndefined();
      expect(list.fields).toBeUndefined();
      expect(oddCode.code).toBeUndefined();
      expect(oddCode.detail).toBe("x");
    });
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
