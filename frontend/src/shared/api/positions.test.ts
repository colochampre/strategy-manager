import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { createElement } from "react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { fetchOpenPositions, notShown, ofExchange, ofPool, ofStrategy, unmatched, useOpenPositions } from "@/shared/api/positions";
import { lock, openOrder, openPosition, openState, unlock } from "@/test/harness";

function respond(body: unknown, status = 200) {
  const fetchMock = vi.fn(() =>
    Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) } as Response),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(unlock);
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

/** A position the facts could not decorate: its nullable fields are null, never omitted. */
const NO_FACTS = openPosition({
  strategy_id: null,
  strategy_archived: null,
  figures_missing: "NO_FACTS",
  side: null,
  base_currency: null,
  size: null,
  opened_size: null,
  entry_price: null,
  opened_at: null,
  fill_count: 0,
  fees: null,
  other_fees: [],
  margin_granted: null,
  leverage: null,
  reservation_status: null,
});

function without<T extends object>(value: T, key: keyof T): unknown {
  return Object.fromEntries(Object.entries(value).filter(([name]) => name !== key));
}

describe("fetchOpenPositions", () => {
  it("returns a well-formed body as the route sent it", async () => {
    const body = openState([openPosition()], [openOrder()]);
    respond(body);

    expect(await fetchOpenPositions()).toEqual(body);
  });

  it("asks GET /positions/open and nothing else", async () => {
    const fetchMock = respond(openState());

    await fetchOpenPositions();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit | undefined];
    expect(url.endsWith("/positions/open")).toBe(true);
    expect(init?.method ?? "GET").toBe("GET");
  });

  it("refuses the WHOLE answer when one element is bad, and never returns the good ones", async () => {
    respond(openState([openPosition(), { ...openPosition(), allocation_id: undefined } as unknown as ReturnType<typeof openPosition>]));

    await expect(fetchOpenPositions()).rejects.toBeInstanceOf(ApiError);
  });

  it("refuses an element with no pool.exchange, or an empty one", async () => {
    const noExchange = { ...openPosition(), pool: { venue: "usdt-m", settlement_currency: "USDT" } };
    respond(openState([noExchange as unknown as ReturnType<typeof openPosition>]));
    await expect(fetchOpenPositions()).rejects.toBeInstanceOf(ApiError);

    const emptyExchange = openPosition({ pool: { exchange: "", venue: "usdt-m", settlement_currency: "USDT" } });
    respond(openState([emptyExchange]));
    await expect(fetchOpenPositions()).rejects.toBeInstanceOf(ApiError);
  });

  it.each([
    ["an empty venue", { exchange: "bybit", venue: "", settlement_currency: "USDT" }],
    ["an empty settlement currency", { exchange: "bybit", venue: "usdt-m", settlement_currency: "" }],
    ["no pool at all", undefined],
  ])("refuses an order with %s", async (_label, pool) => {
    respond(openState([], [{ ...openOrder(), pool } as unknown as ReturnType<typeof openOrder>]));

    await expect(fetchOpenPositions()).rejects.toBeInstanceOf(ApiError);
  });

  it("accepts a NO_FACTS position, whose nullable fields are null", async () => {
    respond(openState([NO_FACTS]));

    const answer = await fetchOpenPositions();

    expect(answer.positions).toHaveLength(1);
    expect(answer.positions[0]?.opened_at).toBeNull();
    expect(answer.positions[0]?.leverage).toBeNull();
  });

  it.each(["opened_at", "fees", "margin_granted", "leverage", "strategy_id", "side", "venue_disagreement"] as const)(
    "refuses a position whose %s is missing, where null would be accepted",
    async (key) => {
      respond(openState([without(NO_FACTS, key) as ReturnType<typeof openPosition>]));

      await expect(fetchOpenPositions()).rejects.toBeInstanceOf(ApiError);
    },
  );

  it("accepts an order whose strategy_name is null (N3), and one the facts could not decorate", async () => {
    respond(
      openState(
        [],
        [
          openOrder({ strategy_name: null }),
          openOrder({ strategy_id: null, strategy_archived: null, strategy_name: null, action: null, submitted_at: null }),
        ],
      ),
    );

    const answer = await fetchOpenPositions();

    expect(answer.orders).toHaveLength(2);
    expect(answer.orders[0]?.strategy_name).toBeNull();
  });

  it.each([
    ["a list instead of an object", []],
    ["no positions list", { as_of: "2026-10-12T21:40:03Z", orders: [] }],
    ["no orders list", { as_of: "2026-10-12T21:40:03Z", positions: [] }],
    ["no as_of", { positions: [], orders: [] }],
    ["an as_of that is not a time", { as_of: "yesterday", positions: [], orders: [] }],
    ["a position that is not an object", { as_of: "2026-10-12T21:40:03Z", positions: ["x"], orders: [] }],
    ["null", null],
  ])("refuses %s instead of reading it as nothing open", async (_label, body) => {
    respond(body);

    await expect(fetchOpenPositions()).rejects.toBeInstanceOf(ApiError);
  });

  it("refuses an origin it does not know on a position and on an order", async () => {
    respond(openState([{ ...openPosition(), origin: "paper" } as unknown as ReturnType<typeof openPosition>]));
    await expect(fetchOpenPositions()).rejects.toBeInstanceOf(ApiError);

    respond(openState([], [{ ...openOrder(), origin: "mixed" } as unknown as ReturnType<typeof openOrder>]));
    await expect(fetchOpenPositions()).rejects.toBeInstanceOf(ApiError);
  });

  it("treats a 404 as an error, unlike the pool report's 404", async () => {
    respond({ detail: "Not Found" }, 404);

    const failure = await fetchOpenPositions().then(
      () => null,
      (error: unknown) => error,
    );

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(404);
  });
});

describe("useOpenPositions", () => {
  it("reads under the key ['positions','open'], stale and refetched every 60 s, with the client's focus default", () => {
    respond(openState());
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);

    renderHook(() => useOpenPositions(), { wrapper });

    const query = client.getQueryCache().find({ queryKey: ["positions", "open"] });
    expect(query).toBeDefined();
    // The cache's `options` type is the base one; the observer's options (stale time, interval) ride on the same object.
    const options = query?.options as unknown as Record<string, unknown> | undefined;
    expect(options?.staleTime).toBe(60_000);
    expect(options?.refetchInterval).toBe(60_000);
    expect(options?.refetchOnWindowFocus).toBeUndefined();
    expect(client.getQueryCache().getAll()).toHaveLength(1);
  });
});

const ALPHA = "11111111-1111-4111-8111-111111111111";
const BETA = "22222222-2222-4222-8222-222222222222";
const GAMMA = "33333333-3333-4333-8333-333333333333";

const BINANCE = { exchange: "binance", venue: "usdt-m", settlement_currency: "USDT" };
const BYBIT_USDT_M = { exchange: "bybit", venue: "usdt-m", settlement_currency: "USDT" };
const BYBIT_SPOT = { exchange: "bybit", venue: "spot", settlement_currency: "USDT" };
const BYBIT_USDC = { exchange: "bybit", venue: "usdt-m", settlement_currency: "USDC" };

/** Two exchanges, three pools of one of them, a null strategy id, an unknown one and an order of each kind. */
const STATE = openState(
  [
    openPosition({ strategy_id: ALPHA, pool: BYBIT_USDT_M }),
    openPosition({ strategy_id: BETA, pool: BYBIT_USDT_M }),
    openPosition({ strategy_id: GAMMA, pool: BYBIT_USDT_M }),
    openPosition({ strategy_id: null, pool: BYBIT_USDT_M }),
    openPosition({ strategy_id: ALPHA, pool: BYBIT_SPOT }),
    openPosition({ strategy_id: BETA, pool: BYBIT_USDC }),
    openPosition({ strategy_id: ALPHA, pool: BINANCE }),
    openPosition({ strategy_id: null, pool: BINANCE }),
  ],
  [
    openOrder({ strategy_id: ALPHA, pool: BYBIT_USDT_M }),
    openOrder({ strategy_id: null, strategy_name: null, pool: BYBIT_USDT_M }),
    openOrder({ strategy_id: BETA, pool: BINANCE }),
  ],
);

describe("ofExchange", () => {
  it("keeps exactly the elements whose pool.exchange is that string, and keeps as_of", () => {
    const bybit = ofExchange(STATE, "bybit");
    expect(bybit.positions).toHaveLength(6);
    expect(bybit.orders).toHaveLength(2);
    expect(bybit.positions.every((position) => position.pool.exchange === "bybit")).toBe(true);
    expect(bybit.as_of).toBe(STATE.as_of);

    const binance = ofExchange(STATE, "binance");
    expect(binance.positions).toHaveLength(2);
    expect(binance.orders).toHaveLength(1);
  });

  it("matches the string exactly: not a prefix, a substring or another case", () => {
    expect(ofExchange(STATE, "byb").positions).toEqual([]);
    expect(ofExchange(STATE, "ybit").positions).toEqual([]);
    expect(ofExchange(STATE, "Bybit").positions).toEqual([]);
    expect(ofExchange(STATE, "").orders).toEqual([]);
  });
});

describe("ofPool", () => {
  it("selects by the three values and never by the exchange alone", () => {
    const only = ofPool(STATE, BYBIT_USDT_M);
    expect(only.positions).toHaveLength(4);
    expect(only.orders).toHaveLength(2);
    expect(only.positions.every((position) => position.pool.venue === "usdt-m")).toBe(true);
    expect(only.positions.every((position) => position.pool.settlement_currency === "USDT")).toBe(true);

    expect(ofPool(STATE, BYBIT_SPOT).positions).toHaveLength(1);
    expect(ofPool(STATE, BYBIT_USDC).positions).toHaveLength(1);
    expect(ofPool(STATE, { exchange: "bybit", venue: "linear", settlement_currency: "USDT" }).positions).toEqual([]);
  });
});

describe("ofStrategy", () => {
  it("keeps the positions and the orders of that strategy, and treats a null strategy id as no strategy's", () => {
    const alpha = ofStrategy(STATE, ALPHA);
    expect(alpha.positions).toHaveLength(3);
    expect(alpha.orders).toHaveLength(1);
    expect(alpha.positions.every((position) => position.strategy_id === ALPHA)).toBe(true);

    expect(ofStrategy(STATE, "").positions).toEqual([]);
    expect(ofStrategy(STATE, "null").positions).toEqual([]);
    expect(ofStrategy(STATE, ALPHA).positions.some((position) => position.strategy_id === null)).toBe(false);
  });
});

describe("notShown and unmatched", () => {
  it("returns an element whose strategy_id is null whatever ids are on screen", () => {
    const named = notShown(ofExchange(STATE, "bybit"), new Set([ALPHA, BETA, GAMMA]));

    expect(named.positions.map((position) => position.strategy_id)).toEqual([null]);
    expect(named.orders.map((order) => order.strategy_id)).toEqual([null]);
  });

  it("returns an element whose strategy is not among the ids on screen, matched by id and never by name", () => {
    const alphaNamedBeta = openPosition({ strategy_id: ALPHA, strategy_name: "Beta" });
    const state = openState([alphaNamedBeta, openPosition({ strategy_id: BETA, strategy_name: "Beta" })]);

    const named = notShown(state, new Set([BETA]));

    expect(named.positions.map((position) => position.strategy_id)).toEqual([ALPHA]);
  });

  it("unmatched returns the null ones and no element with a strategy id", () => {
    const state = ofExchange(STATE, "bybit");

    const none = unmatched(state);

    expect(none.positions.map((position) => position.strategy_id)).toEqual([null]);
    expect(none.orders.map((order) => order.strategy_id)).toEqual([null]);
    expect(unmatched(openState([openPosition({ strategy_id: ALPHA })])).positions).toEqual([]);
  });

  it("over one fixture the positions of an exchange are the union of its visible strategies' and notShown, with nothing in both", () => {
    const bybit = ofExchange(STATE, "bybit");
    const visible = new Set([ALPHA, BETA]);

    const onRows = [...visible].flatMap((id) => ofStrategy(bybit, id).positions);
    const named = notShown(bybit, visible).positions;

    const ids = (list: ReadonlyArray<{ allocation_id: string }>) => list.map((position) => position.allocation_id).sort();
    expect(ids([...onRows, ...named])).toEqual(ids(bybit.positions));
    const inBoth = onRows.filter((row) => named.some((other) => other.allocation_id === row.allocation_id));
    expect(inBoth).toEqual([]);

    const orderIds = (list: ReadonlyArray<{ attempt_id: string }>) => list.map((order) => order.attempt_id).sort();
    const orderRows = [...visible].flatMap((id) => ofStrategy(bybit, id).orders);
    expect(orderIds([...orderRows, ...notShown(bybit, visible).orders])).toEqual(orderIds(bybit.orders));
  });
});
