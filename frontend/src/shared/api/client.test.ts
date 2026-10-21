import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
import { page } from "@/shared/auth/reauthenticate";

function fakeResponse(body: unknown, status: number, ok: boolean = status >= 200 && status < 300): Response {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
  } as Response;
}

describe("apiFetch", () => {
  let reload: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    reload = vi.spyOn(page, "reload").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("prefixes every call with the API base URL and the /api prefix", async () => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ ok: true }, 200));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/reconciliation/confirmed");

    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/reconciliation/confirmed`);
  });

  it("sends no credential of its own: Cloudflare Access signs the request", async () => {
    window.localStorage.setItem("sm.admin_token", JSON.stringify({ state: { token: "left-over" } }));
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ ok: true }, 200));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/reconciliation/confirmed");

    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(call[1].headers).get("Authorization")).toBeNull();
  });

  it("reloads the page on a 401, so an expired Access session signs in again, and still throws", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse({ detail: "unauthorized" }, 401, false)));

    await expect(apiFetch("/reconciliation/confirmed")).rejects.toMatchObject({ status: 401 });

    expect(reload).toHaveBeenCalledTimes(1);
  });

  it.each([403, 503, 500])("does not reload on a %i", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse({ detail: "no" }, status, false)));

    await expect(apiFetch("/reconciliation/confirmed")).rejects.toBeInstanceOf(ApiError);

    expect(reload).not.toHaveBeenCalled();
  });

  it.each([
    [409, { outcome: "SUPERSEDED", detail: "the observation moved" }],
    [503, { outcome: "DRY_RUN_REFUSED", detail: "dry run" }],
    [422, { outcome: "REASON_REQUIRED", detail: "a reason is required" }],
  ] as const)("throws a typed ApiError carrying outcome and detail on a %i refusal", async (status, body) => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse(body, status, false));
    vi.stubGlobal("fetch", fetchMock);

    const error = (await apiFetch("/strategies/id/enable", { method: "POST" }).catch(
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

  describe("responseBody", () => {
    function unreadable(message: string): Response {
      return {
        ok: false,
        status: 500,
        json: () => Promise.reject(new SyntaxError(message)),
      } as unknown as Response;
    }

    async function refusalOf(response: Response): Promise<ApiError> {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
      return (await apiFetch("/credentials/bybit", { method: "DELETE" }).catch(
        (caught: unknown) => caught,
      )) as ApiError;
    }

    it("is the whole body of a refusal that carries lists at its top level", async () => {
      const body = {
        outcome: "STRATEGIES_ENABLED",
        detail: "strategies are enabled",
        enabled_strategies: ["alpha"],
        symbols: ["BTCUSDT"],
        allocations: ["a-1"],
        live_reservations: ["r-1"],
        in_flight_attempts: ["x-1"],
      };

      const error = await refusalOf(fakeResponse(body, 409, false));

      expect(error.responseBody).toEqual(body);
    });

    it("is the body of a flat refusal while fields stays undefined", async () => {
      const error = await refusalOf(fakeResponse({ detail: "x" }, 404, false));

      expect(error.responseBody).toEqual({ detail: "x" });
      expect(error.fields).toBeUndefined();
    });

    it.each([
      ["an array", () => fakeResponse([{ detail: "x" }], 422, false)],
      ["a string", () => fakeResponse("boom", 502, false)],
      ["null", () => fakeResponse(null, 500, false)],
      ["an empty body", () => unreadable("Unexpected end of JSON input")],
      ["a body that is not JSON", () => unreadable("Unexpected token < in JSON at position 0")],
    ])("is undefined when the body is %s", async (_label, response) => {
      const error = await refusalOf(response());

      expect(error).toBeInstanceOf(ApiError);
      expect(error.responseBody).toBeUndefined();
    });

    it.each([
      {
        shape: "a body with top-level lists",
        status: 409,
        body: { outcome: "STRATEGIES_ENABLED", detail: "enabled", symbols: ["BTCUSDT"] },
        expected: {
          outcome: "STRATEGIES_ENABLED",
          detail: "enabled",
          code: "STRATEGIES_ENABLED",
          fields: undefined,
          message: "enabled",
        },
      },
      {
        shape: "a flat body",
        status: 404,
        body: { detail: "x" },
        expected: { outcome: undefined, detail: "x", code: undefined, fields: undefined, message: "x" },
      },
      {
        shape: "a structured detail",
        status: 422,
        body: { detail: { error: "KEY_REJECTED", message: "no" } },
        expected: {
          outcome: undefined,
          detail: "no",
          code: "KEY_REJECTED",
          fields: { error: "KEY_REJECTED", message: "no" },
          message: "no",
        },
      },
      {
        shape: "a list detail",
        status: 422,
        body: { detail: [{ loc: ["body", "api_key"], msg: "short" }] },
        expected: {
          outcome: undefined,
          detail: undefined,
          code: undefined,
          fields: undefined,
          message: "Request failed with status 422",
        },
      },
      {
        shape: "an array",
        status: 422,
        body: [{ detail: "x" }],
        expected: {
          outcome: undefined,
          detail: undefined,
          code: undefined,
          fields: undefined,
          message: "Request failed with status 422",
        },
      },
      {
        shape: "a string",
        status: 502,
        body: "boom",
        expected: {
          outcome: undefined,
          detail: undefined,
          code: undefined,
          fields: undefined,
          message: "Request failed with status 502",
        },
      },
      {
        shape: "null",
        status: 500,
        body: null,
        expected: {
          outcome: undefined,
          detail: undefined,
          code: undefined,
          fields: undefined,
          message: "Request failed with status 500",
        },
      },
    ])("leaves status, outcome, detail, code, fields and message as they were for $shape", async (row) => {
      const error = await refusalOf(fakeResponse(row.body, row.status, false));

      expect(error.status).toBe(row.status);
      expect(error.outcome).toBe(row.expected.outcome);
      expect(error.detail).toBe(row.expected.detail);
      expect(error.code).toBe(row.expected.code);
      expect(error.fields).toEqual(row.expected.fields);
      expect(error.message).toBe(row.expected.message);
    });

    describe("an error never holds the request body", () => {
      const sentinel = "SENTINEL-REQUEST-SECRET-0123456789";

      function textsOf(root: unknown): string[] {
        const seen = new Set<unknown>();
        const found: string[] = [];
        const walk = (value: unknown): void => {
          if (typeof value === "string") {
            found.push(value);
            return;
          }
          if (typeof value !== "object" || value === null || seen.has(value)) {
            return;
          }
          seen.add(value);
          for (const name of Object.getOwnPropertyNames(value)) {
            found.push(name);
            walk((value as Record<string, unknown>)[name]);
          }
        };
        walk(root);
        return found;
      }

      async function failingPut(answer: () => Promise<Response>): Promise<ApiError> {
        vi.stubGlobal("fetch", vi.fn().mockImplementation(answer));
        return (await apiFetch("/credentials/bybit", {
          method: "PUT",
          body: JSON.stringify({ api_key: sentinel, api_secret: sentinel }),
        }).catch((caught: unknown) => caught)) as ApiError;
      }

      it.each([
        ["a 422", () => Promise.resolve(fakeResponse({ detail: "refused" }, 422, false))],
        ["a 500", () => Promise.resolve(fakeResponse({ detail: "broken" }, 500, false))],
        ["no answer at all", () => Promise.reject(new TypeError("Failed to fetch"))],
      ])("after %s", async (_label, answer) => {
        const error = await failingPut(answer);

        expect(error).toBeInstanceOf(ApiError);
        const everything = [error.message, ...textsOf(error)];
        expect(everything.length).toBeGreaterThan(1);
        for (const text of everything) {
          expect(text).not.toContain(sentinel);
        }
      });
    });
  });

  it("throws a typed ApiError for a plain FastAPI 404 body, never a resolved value", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(fakeResponse({ detail: "no such strategy" }, 404, false));
    vi.stubGlobal("fetch", fetchMock);

    const error = (await apiFetch("/strategies/unknown").catch(
      (caught: unknown) => caught,
    )) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(404);
    expect(error.detail).toBe("no such strategy");
  });

  it("throws a typed ApiError for a 500 with a non-JSON error body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.reject(new SyntaxError("Unexpected token in JSON")),
    } as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);

    const error = (await apiFetch("/reconciliation/confirmed").catch((caught: unknown) => caught)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(500);
  });

  it("never resolves a non-2xx response as success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ outcome: "SUPERSEDED", detail: "x" }, 409, false));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiFetch("/strategies/id/enable", { method: "POST" })).rejects.toBeInstanceOf(ApiError);
  });

  it("throws a typed ApiError on a network failure, never undefined", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    const error = await apiFetch("/reconciliation/confirmed").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).not.toBeUndefined();
  });

  it("resolves the parsed JSON body on a 2xx response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ outcome: "ENABLED" }, 200));
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiFetch<{ outcome: string }>("/strategies/id/enable", {
      method: "POST",
    });

    expect(result).toEqual({ outcome: "ENABLED" });
  });
});
