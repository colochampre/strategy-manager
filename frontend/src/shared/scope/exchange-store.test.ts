import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  distinctExchanges,
  EXCHANGE_STORAGE_KEY,
  isExchangeScoped,
  resolveExchange,
  useExchangeScope,
  useExchangeStore,
} from "@/shared/scope/exchange-store";
import {
  type ExtraRoute,
  heldSubscription,
  jsonResponse,
  pool,
  resetExchangeScope,
  storedKey,
  stubApi,
} from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
}

async function readyScope(pools: unknown) {
  stubApi(HEALTH, [], { kind: "ok", body: pools });
  const hook = renderHook(() => useExchangeScope(), { wrapper: wrapper() });
  await waitFor(() => expect(hook.result.current.status).toBe("ready"));
  const scope = hook.result.current;
  if (scope.status !== "ready") throw new Error("scope not ready");
  return { ...hook, scope };
}

beforeEach(() => {
  resetExchangeScope();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("options", () => {
  it("test_options_are_distinct_exchanges_from_pools_default_is_first", async () => {
    const { scope } = await readyScope([
      pool("bybit", "linear"),
      pool("binance"),
      pool("bybit", "spot"),
      pool("binance", "coin-m", "BTC"),
    ]);

    expect(scope.options).toEqual(["bybit", "binance"]);
    expect(scope.exchange).toBe("bybit");
  });

  it("deduplicates and keeps first-seen order", () => {
    expect(distinctExchanges([pool("b"), pool("a"), pool("b"), pool("c"), pool("a")])).toEqual([
      "b",
      "a",
      "c",
    ]);
    expect(distinctExchanges([])).toEqual([]);
  });

  it("resolves to the default when nothing is selected", () => {
    expect(resolveExchange(["bybit", "binance"], null)).toBe("bybit");
  });

  it("keeps a selection that is among the options", () => {
    expect(resolveExchange(["bybit", "binance"], "binance")).toBe("binance");
  });

  it("falls back to the default when the selection is no longer an option", () => {
    expect(resolveExchange(["bybit", "binance"], "kraken")).toBe("bybit");
  });

  it("has no exchange when there are no options", () => {
    expect(resolveExchange([], "bybit")).toBeNull();
    expect(resolveExchange([], null)).toBeNull();
  });

  it("follows a selection made through the scope", async () => {
    const { result } = await readyScope([pool("bybit"), pool("binance")]);

    act(() => {
      if (result.current.status === "ready") result.current.select("binance");
    });

    const scope = result.current;
    if (scope.status !== "ready") throw new Error("scope not ready");
    expect(scope.exchange).toBe("binance");
  });

  it("is loading while pools load, never ready with a guessed exchange", () => {
    stubApi(HEALTH, [], { kind: "pending" });

    const { result } = renderHook(() => useExchangeScope(), { wrapper: wrapper() });

    expect(result.current.status).toBe("loading");
  });

  it("is an error when pools fail, never ready with no options", async () => {
    stubApi(HEALTH, [], { kind: "status", status: 500, body: { detail: "boom" } });

    const { result } = renderHook(() => useExchangeScope(), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.status).toBe("error"));
  });

  it("is an error when the pools body is not a list of pools", async () => {
    for (const body of [{ items: [] }, [{ exchange: "bybit" }], [null]]) {
      stubApi(HEALTH, [], { kind: "ok", body });
      const { result, unmount } = renderHook(() => useExchangeScope(), { wrapper: wrapper() });
      await waitFor(() => expect(result.current.status).toBe("error"));
      unmount();
    }
  });
});

describe("tabs only where something runs", () => {
  const BOTH = [pool("bybit"), pool("binance")];

  function route(strategies: unknown, held: unknown): ExtraRoute {
    return (url) => {
      if (url.includes("/strategies")) return strategies === PENDING ? new Promise<Response>(() => undefined) : answer(strategies);
      if (url.endsWith("/subscriptions/held")) return held === PENDING ? new Promise<Response>(() => undefined) : answer(held);
      return undefined;
    };
  }
  const PENDING = Symbol("pending");
  function answer(body: unknown) {
    return Promise.resolve(body === FAILS ? jsonResponse({ detail: "boom" }, 500) : jsonResponse(body));
  }
  const FAILS = Symbol("fails");

  async function scopeWith(strategies: unknown, held: unknown, credentials: unknown[]) {
    stubApi(HEALTH, [], { kind: "ok", body: BOTH }, {}, route(strategies, held), {}, { kind: "ok", body: credentials });
    const hook = renderHook(() => useExchangeScope(), { wrapper: wrapper() });
    await waitFor(() => expect(hook.result.current.status).toBe("ready"));
    return hook;
  }

  function optionsOf(result: { current: ReturnType<typeof useExchangeScope> }) {
    const scope = result.current;
    if (scope.status !== "ready") throw new Error("scope not ready");
    return scope;
  }

  it("drops the exchange that only has a pool once every source has answered", async () => {
    const { result } = await scopeWith([], [], [storedKey("binance")]);

    await waitFor(() => expect(optionsOf(result).options).toEqual(["binance"]));
    expect(optionsOf(result).exchange).toBe("binance");
  });

  it("shows an exchange that only an active subscription runs on", async () => {
    const { result } = await scopeWith([], [heldSubscription({ exchange: "bybit" })], []);

    await waitFor(() => expect(optionsOf(result).options).toEqual(["bybit"]));
  });

  it("keeps the pool exchanges while a source is still loading", async () => {
    const { result } = await scopeWith([], PENDING, [storedKey("binance")]);

    await waitFor(() => expect(optionsOf(result).options).toEqual(["bybit", "binance"]));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(optionsOf(result).options).toEqual(["bybit", "binance"]);
  });

  it("keeps the pool exchanges when a source failed", async () => {
    const { result } = await scopeWith(FAILS, [], [storedKey("binance")]);

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(optionsOf(result).options).toEqual(["bybit", "binance"]);
  });

  it("resolves a stored selection that no longer runs to the first tab left", async () => {
    window.localStorage.setItem("sm.exchange", JSON.stringify({ state: { selected: "bybit" }, version: 0 }));
    await useExchangeStore.persist.rehydrate();

    const { result } = await scopeWith([], [], [storedKey("binance")]);

    await waitFor(() => expect(optionsOf(result).exchange).toBe("binance"));
  });
});

describe("persistence", () => {
  it("test_persisted_through_safe_storage_key_sm_exchange", () => {
    expect(EXCHANGE_STORAGE_KEY).toBe("sm.exchange");

    useExchangeStore.getState().select("binance");

    const raw = window.localStorage.getItem("sm.exchange");
    expect(raw).not.toBeNull();
    expect(JSON.parse(raw as string).state.selected).toBe("binance");
  });

  it("restores a persisted selection that is still an option", async () => {
    window.localStorage.setItem(
      "sm.exchange",
      JSON.stringify({ state: { selected: "binance" }, version: 0 }),
    );
    await useExchangeStore.persist.rehydrate();

    const { scope } = await readyScope([pool("bybit"), pool("binance")]);

    expect(scope.exchange).toBe("binance");
  });

  it("falls back to the default when the persisted exchange is no longer an option", async () => {
    window.localStorage.setItem(
      "sm.exchange",
      JSON.stringify({ state: { selected: "kraken" }, version: 0 }),
    );
    await useExchangeStore.persist.rehydrate();

    const { scope } = await readyScope([pool("bybit"), pool("binance")]);

    expect(scope.exchange).toBe("bybit");
  });

  it("survives a persisted value of the wrong type", async () => {
    window.localStorage.setItem("sm.exchange", JSON.stringify({ state: { selected: 42 }, version: 0 }));
    await useExchangeStore.persist.rehydrate();

    const { scope } = await readyScope([pool("bybit")]);

    expect(scope.exchange).toBe("bybit");
  });

  it("survives corrupt persisted JSON", async () => {
    window.localStorage.setItem("sm.exchange", "{not json");

    await expect(useExchangeStore.persist.rehydrate()).resolves.not.toThrow();
    expect(useExchangeStore.getState().selected).toBeNull();
  });

  // These two degrade the store's storage wrapper to memory for the rest of
  // the file, so they stay last.
  it("never breaks the page when storage throws on write (private mode)", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    expect(() => useExchangeStore.getState().select("binance")).not.toThrow();
    expect(useExchangeStore.getState().selected).toBe("binance");
  });

  it("never breaks the page when the storage accessor itself throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    await expect(useExchangeStore.persist.rehydrate()).resolves.not.toThrow();
    expect(() => useExchangeStore.getState().select("bybit")).not.toThrow();
  });
});

describe("scoped routes", () => {
  it.each(["/", "/strategies/authored", "/strategies/authored/", "/strategies/5b0c7a52-6f43-4d6e-9c1c-0c2f3f3f2a11"])(
    "%s is exchange-scoped",
    (path) => {
      expect(isExchangeScoped(path)).toBe(true);
    },
  );

  it.each([
    "/settings",
    "/settings/",
    "/nope",
    "/strategies/a/b",
    "/no/such/page",
    "/strategies",
    "/strategies/",
    "/strategies/explore",
    "/strategies/explore/",
    "/strategies/explore/5b0c7a52-6f43-4d6e-9c1c-0c2f3f3f2a11",
  ])(
    "%s is not exchange-scoped",
    (path) => {
      expect(isExchangeScoped(path)).toBe(false);
    },
  );

  it("test_settings_route_reads_no_exchange_scope", () => {
    expect(isExchangeScoped("/settings")).toBe(false);
  });
});
