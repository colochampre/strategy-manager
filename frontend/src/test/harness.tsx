import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

import type { BookedItem, ConfirmedDiscrepancy, ConfirmedReading } from "@/shared/api/discrepancies";
import type { InFlightOrder, OpenPosition, OpenState } from "@/shared/api/positions";
import type { Subscription } from "@/shared/api/types";
import { page } from "@/shared/auth/reauthenticate";
import { useExchangeStore } from "@/shared/scope/exchange-store";

export type HealthStub =
  | { kind: "ok"; body: unknown }
  | { kind: "status"; status: number; body?: unknown }
  | { kind: "network-error" }
  | { kind: "pending" };

export type PoolsStub =
  | { kind: "ok"; body: unknown }
  | { kind: "status"; status: number; body?: unknown }
  | { kind: "network-error" }
  | { kind: "pending" };

export type CredentialsStub = PoolsStub;
export type PerformanceStub = PoolsStub;
export type AvailablePairsStub = PoolsStub;
export type OpenPositionsStub = PoolsStub;

/**
 * What `GET /reconciliation/confirmed` answers: a body, a status (a 404, a 500), a network error, or a
 * request that never answers (`pending`, for loading). `sequence` answers the first request with the first
 * stub, the second with the second, and every later one with the last, so a test can read well and then fail.
 */
export type ConfirmedStub = PoolsStub | { kind: "sequence"; stubs: PoolsStub[] };

let placeholderSequence = 0;

/** A placeholder id of the form `<prefix>-0001`, counting up per call, so two builders never collide on a key. */
function placeholderId(prefix: string): string {
  placeholderSequence += 1;
  return `${prefix}-${String(placeholderSequence).padStart(4, "0")}`;
}

/** The three lists of `GET /reconciliation/confirmed` hold these: a NOT_BOOKED full close of "Alpha" on Bybit USDT-M. */
export function discrepancy(overrides: Partial<ConfirmedDiscrepancy> = {}): ConfirmedDiscrepancy {
  return {
    discrepancy_id: placeholderId("discrepancy"),
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    symbol: "SOLUSDT",
    kind: "ATTRIBUTABLE_FULL_CLOSE",
    reason: "NOT_BOOKED",
    venue_net_base: "0",
    ledger_net_base: "0.5",
    allocations: [
      {
        allocation_id: placeholderId("allocation"),
        strategy_id: "11111111-1111-4111-8111-111111111111",
        strategy_name: "Alpha",
      },
    ],
    confirmed_at: "2026-10-16T21:31:00Z",
    last_observed_at: "2026-10-16T21:39:42Z",
    user_email: "owner@example.com",
    ...overrides,
  };
}

/** One automatic booking of the `booked` list: a SELL of 0.5 SOL by "Alpha", its discrepancy already resolved. */
export function booking(overrides: Partial<BookedItem> = {}): BookedItem {
  return {
    proposal_id: placeholderId("proposal"),
    discrepancy_id: placeholderId("discrepancy"),
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    symbol: "SOLUSDT",
    kind: "ATTRIBUTABLE_FULL_CLOSE",
    strategy_id: "11111111-1111-4111-8111-111111111111",
    strategy_name: "Alpha",
    allocation_id: placeholderId("allocation"),
    side: "SELL",
    quantity: "0.5",
    fill_count: 1,
    decided_at: "2026-10-16T21:33:00Z",
    decided_by: "automatic",
    execution_attempt_id: null,
    discrepancy_open: false,
    ...overrides,
  };
}

/**
 * The whole body of `GET /reconciliation/confirmed`: all three lists empty and `dry_run` false unless a
 * test says otherwise. `needs_owner_count` follows `needs_owner` unless it is overridden.
 */
export function confirmedBody(overrides: Partial<ConfirmedReading> = {}): ConfirmedReading {
  const needsOwner = overrides.needs_owner ?? [];
  return {
    read_at: "2026-10-16T21:40:03Z",
    dry_run: false,
    needs_owner_count: needsOwner.length,
    needs_owner: needsOwner,
    being_booked: [],
    booked: [],
    ...overrides,
  };
}

/** What `GET /pools/{exchange}/{venue}/{ccy}/available-pairs` answers for a pool, in the API's shape. */
export function availablePairs(exchange: string, venue: string, currency: string, pairs: readonly string[]) {
  return {
    pool: { exchange, venue, settlement_currency: currency },
    pairs: [...pairs],
    count: pairs.length,
  };
}

export function pool(
  exchange: string,
  venue = "usdt-m",
  settlementCurrency = "USDT",
  balance: { total: string; available: string; observed_at: string; stale: boolean } | null = null,
) {
  return {
    exchange,
    venue,
    settlement_currency: settlementCurrency,
    enabled: true,
    balance,
    reserved: "0",
    allocatable: balance === null ? null : balance.available,
  };
}

let elementSequence = 0;

/** A fresh id in the shape of a UUID, so two builders never collide on a key. */
function nextElementId(): string {
  elementSequence += 1;
  return `00000000-0000-4000-8000-${String(elementSequence).padStart(12, "0")}`;
}

/**
 * One position of `GET /positions/open`, in the route's shape: a live LONG on `SOLUSDT` of the strategy
 * "Alpha" in the Bybit USDT-M pool, every figure present. The overrides replace any field.
 */
export function openPosition(overrides: Partial<OpenPosition> = {}): OpenPosition {
  return {
    allocation_id: nextElementId(),
    strategy_id: "11111111-1111-4111-8111-111111111111",
    strategy_name: "Alpha",
    strategy_archived: false,
    pool: { exchange: "bybit", venue: "usdt-m", settlement_currency: "USDT" },
    currency: "USDT",
    markets: ["SOLUSDT"],
    origin: "live",
    figures_missing: null,
    side: "LONG",
    base_currency: "SOL",
    size: "0.5",
    opened_size: "0.5",
    entry_price: "184.300000000000000000",
    opened_at: "2026-10-12T14:05:11Z",
    fill_count: 1,
    fees: "0.25",
    other_fees: [],
    margin_granted: "30.00",
    leverage: "3.00000000",
    reservation_status: "FILLED",
    venue_disagreement: null,
    ...overrides,
  };
}

/** One order in flight of `GET /positions/open`: a live opening order of "Alpha" on `SOLUSDT`, sent at 21:12 UTC. */
export function openOrder(overrides: Partial<InFlightOrder> = {}): InFlightOrder {
  return {
    attempt_id: nextElementId(),
    strategy_id: "11111111-1111-4111-8111-111111111111",
    strategy_archived: false,
    strategy_name: "Alpha",
    pool: { exchange: "bybit", venue: "usdt-m", settlement_currency: "USDT" },
    market: "SOLUSDT",
    action: "OPEN",
    origin: "live",
    submitted_at: "2026-10-12T21:12:00Z",
    ...overrides,
  };
}

/** The whole body of `GET /positions/open`, read at 21:40:03 UTC unless a test says otherwise. */
export function openState(
  positions: OpenPosition[] = [],
  orders: InFlightOrder[] = [],
  asOf = "2026-10-12T21:40:03Z",
): OpenState {
  return { as_of: asOf, positions, orders };
}

/** One `STORED` row of `GET /credentials`, in the API's shape; the overrides replace any of its fields. */
export function storedKey(exchange: string, overrides: Record<string, unknown> = {}) {
  return {
    exchange,
    status: "STORED",
    label: "default",
    last4: "1234",
    stored_at: "2026-10-01T10:00:00Z",
    validated_at: "2026-10-01T10:00:00Z",
    trade_capable: true,
    trade_capability_source: "VERIFIED",
    trade_confirmed_at: null,
    withdraw_check: "VERIFIED",
    withdraw_confirmed_at: null,
    internal_transfer: false,
    ...overrides,
  };
}

/**
 * What `GET /credentials` answers when a test names no credentials: one key
 * that trades per DISTINCT exchange of a pools list, so in every shell test
 * each exchange has a key and no tab gains a mark; an empty list for any other
 * pools stub. Without it the stub would reject the read, `apiFetch` would turn
 * that into an error, and every shell test would stay green with the read
 * failing inside it.
 */
function defaultCredentials(pools: PoolsStub): CredentialsStub {
  if (pools.kind !== "ok" || !Array.isArray(pools.body)) return { kind: "ok", body: [] };
  const exchanges: string[] = [];
  for (const row of pools.body as ({ exchange?: unknown } | null)[]) {
    const exchange = row?.exchange;
    if (typeof exchange === "string" && !exchanges.includes(exchange)) exchanges.push(exchange);
  }
  return { kind: "ok", body: exchanges.map((exchange) => storedKey(exchange)) };
}

/** One `EMPTY` row of `GET /credentials`: the exchange and its status, everything else null. */
export function emptyKey(exchange: string) {
  return {
    exchange,
    status: "EMPTY",
    label: null,
    last4: null,
    stored_at: null,
    validated_at: null,
    trade_capable: null,
    trade_capability_source: null,
    trade_confirmed_at: null,
    withdraw_check: null,
    withdraw_confirmed_at: null,
    internal_transfer: null,
  };
}

/** What `GET /performance/pools/...` answers for a pool with an empty ledger (the DRY_RUN reality). */
export function emptyPerformance(exchange: string, venue: string, currency: string) {
  return {
    pool: { exchange, venue, settlement_currency: currency },
    currency,
    day_boundary: "UTC",
    trade_count: 0,
    total_pnl: "0",
    max_drawdown: "0.0000000000",
    excluded: {
      open_trade_count: 0,
      rehearsal_fill_count: 0,
      no_capital_at_open: 0,
      unconverted_fee: 0,
      unresolved_allocation_count: 0,
    },
    ranges: ["7D", "30D", "90D", "1Y", "All"].map((range) => ({
      range,
      pnl: "0",
      return: "0.0000000000",
      trade_count: 0,
    })),
    curve: [],
    monthly: [],
  };
}

/** What `GET /strategies/{id}/share-preview` answers for a pool nothing has synced: no balance, so no amount. */
/**
 * The signed-in user's ACTIVE subscription to strategy `strategyId`, at `share` percent of their own pool:
 * what `StrategyView.subscription` holds for the author of a strategy.
 */
export function subscriptionOf(strategyId: string, share = "100", overrides: Partial<Subscription> = {}): Subscription {
  return {
    // Its own id, derived from the strategy's so two strategies' subscriptions never share one.
    id: `99999999-9999-4999-8999-${strategyId.replace(/-/g, "").slice(-12)}`,
    strategy_id: strategyId,
    pool_id: 1,
    allocation_percent: share,
    status: "ACTIVE",
    created_at: "2026-10-27T10:00:00Z",
    left_at: null,
    ended_at: null,
    ...overrides,
  };
}

export function unsyncedSharePreview(id: string, exchange = "bybit", venue = "usdt-m", currency = "USDT") {
  return {
    strategy_id: id,
    pool: { exchange, venue, settlement_currency: currency },
    currency,
    pool_minimum: "5.000000000000000000",
    balance: null,
    exact: null,
    steps: [],
  };
}

/**
 * An `ExtraRoute` that serves one strategy's detail, its empty enable history
 * and its empty performance report and trades list, so a deep link to its page
 * can load. Pass it as `stubApi`'s `extra`.
 */
export function strategyRoute(id: string, name: string, overrides: Record<string, unknown> = {}): ExtraRoute {
  const detail = {
    id,
    name,
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    subscription: subscriptionOf(id),
    enabled: false,
    archived_at: null,
    allowed_pairs: ["ETHUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    visibility: "PRIVATE",
    secret_last4: "x4F2",
    ...overrides,
  };
  return (url) => {
    if (url.includes(`/performance/strategies/${id}/trades`)) {
      return Promise.resolve(jsonResponse({ trades: [], next_cursor: null }));
    }
    if (url.endsWith(`/performance/strategies/${id}`)) {
      return Promise.resolve(
        jsonResponse({ ...emptyPerformance("bybit", "usdt-m", "USDT"), strategy_id: id, by_pair: [] }),
      );
    }
    if (url.includes(`/strategies/${id}/share-preview`)) return Promise.resolve(jsonResponse(unsyncedSharePreview(id)));
    if (url.endsWith(`/strategies/${id}/events`)) return Promise.resolve(jsonResponse([]));
    if (url.endsWith(`/strategies/${id}`)) return Promise.resolve(jsonResponse(detail));
    return undefined;
  };
}

/** One Bybit pool unless a test says otherwise, so the exchange scope is ready. */
const DEFAULT_POOLS: PoolsStub = { kind: "ok", body: [pool("bybit", "usdt-m")] };

/** The venue's spelling (`STXUSDT`), sorted, as the endpoint answers it; a pool without an entry gets these. */
const DEFAULT_AVAILABLE_PAIRS = ["AAVEUSDT", "SFPUSDT", "STXUSDT"] as const;

export function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) } as Response;
}

/**
 * Answers a request a view of its own owns (the strategies endpoints, say), or
 * returns `undefined` to leave it to the shell's routes.
 */
export type ExtraRoute = (url: string, init?: RequestInit) => Promise<Response> | undefined;

/**
 * A `GET /positions/open` that fails with a 500 the first time and holds every later request until `release`
 * answers all of them with `answer`. `requests` counts the calls, so a test can tell a second press that
 * started a request from one that did not.
 */
export function failsOnceThenHolds(answer: unknown) {
  const waiting: Array<() => void> = [];
  let requests = 0;
  const route: ExtraRoute = (url) => {
    if (!url.endsWith("/positions/open")) return undefined;
    requests += 1;
    if (requests === 1) return Promise.resolve(jsonResponse({ detail: "down" }, 500));
    return new Promise<Response>((resolve) => {
      waiting.push(() => resolve(jsonResponse(answer)));
    });
  };
  return {
    route,
    requests: () => requests,
    release: () => waiting.splice(0).forEach((answerNow) => answerNow()),
  };
}

/**
 * Routes the endpoints the shell touches; everything else is a loud failure.
 * `health` answers `GET /health`, which the panel no longer asks: the badge reads `GET /api/me`. A test that
 * needs another mode or the brake released answers `/api/me` itself, through `extra`.
 * The second argument is retired: it answered the booking route, which the panel no longer
 * calls (owner decision 66), and is kept, ignored, only so that the callers that pass `[]` there
 * still compile; a request to that route is now recorded in `unexpected`.
 * `performance` overrides a pool's report, keyed `exchange/venue/ccy`; a pool
 * without an entry answers an empty ledger. `extra` is asked first. `available`
 * overrides a pool's available pairs, keyed `exchange/venue/ccy`; a pool without
 * an entry lists `AAVEUSDT`, `SFPUSDT` and `STXUSDT`. `credentials` overrides the
 * answer to `GET /credentials` (see `defaultCredentials`). Every URL it rejects is
 * recorded in the returned mock's `unexpected` array. `openPositions` overrides
 * the answer to `GET /positions/open`; by default it is a well-formed empty
 * body, `{as_of, positions: [], orders: []}`, so a page that asks for it reads
 * nothing open rather than a rejected request. `confirmed` overrides the answer
 * to `GET /reconciliation/confirmed` (see `ConfirmedStub`); by default it is
 * `confirmedBody()`, three empty lists and `dry_run` false.
 */
export function stubApi(
  health: HealthStub,
  _retired: unknown[] = [],
  pools: PoolsStub = DEFAULT_POOLS,
  performance: Record<string, PerformanceStub> = {},
  extra?: ExtraRoute,
  available: Record<string, AvailablePairsStub> = {},
  credentials?: CredentialsStub,
  openPositions?: OpenPositionsStub,
  confirmed?: ConfirmedStub,
) {
  const unexpected: string[] = [];
  let confirmedRequests = 0;
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const owned = extra?.(url, init);
    if (owned !== undefined) return owned;
    // Who is signed in: the admin after `unlock()`, nobody (401) after `lock()` or by default.
    if (url.endsWith("/api/me")) {
      return Promise.resolve(
        signedIn
          ? jsonResponse({ email: SIGNED_IN_EMAIL, is_admin: true, mode: "SIMULATION", dry_run_brake: true })
          : jsonResponse({ detail: "unauthorized" }, 401),
      );
    }
    if (url.endsWith("/health")) {
      if (health.kind === "network-error") return Promise.reject(new TypeError("offline"));
      if (health.kind === "pending") return new Promise<Response>(() => undefined);
      if (health.kind === "status") return Promise.resolve(jsonResponse(health.body ?? {}, health.status));
      return Promise.resolve(jsonResponse(health.body));
    }
    // The webhook block reads the deployment's public host when it is opened: this deployment names none.
    if (url.endsWith("/webhook-origin")) return Promise.resolve(jsonResponse({ origin: null }));
    const performancePath = /\/performance\/pools\/(.+)$/.exec(url);
    if (performancePath) {
      const key = decodeURIComponent(performancePath[1] ?? "");
      const [exchange = "", venue = "", currency = ""] = key.split("/");
      const stub: PerformanceStub = performance[key] ?? {
        kind: "ok",
        body: emptyPerformance(exchange, venue, currency),
      };
      if (stub.kind === "network-error") return Promise.reject(new TypeError("offline"));
      if (stub.kind === "pending") return new Promise<Response>(() => undefined);
      if (stub.kind === "status") return Promise.resolve(jsonResponse(stub.body ?? {}, stub.status));
      return Promise.resolve(jsonResponse(stub.body));
    }
    const pairsPath = /\/pools\/([^/]+)\/([^/]+)\/([^/]+)\/available-pairs$/.exec(url);
    if (pairsPath) {
      const [exchange = "", venue = "", currency = ""] = pairsPath.slice(1).map((part) => decodeURIComponent(part ?? ""));
      const stub: AvailablePairsStub = available[`${exchange}/${venue}/${currency}`] ?? {
        kind: "ok",
        body: availablePairs(exchange, venue, currency, DEFAULT_AVAILABLE_PAIRS),
      };
      if (stub.kind === "network-error") return Promise.reject(new TypeError("offline"));
      if (stub.kind === "pending") return new Promise<Response>(() => undefined);
      if (stub.kind === "status") return Promise.resolve(jsonResponse(stub.body ?? {}, stub.status));
      return Promise.resolve(jsonResponse(stub.body));
    }
    // GET only: a PUT or a DELETE to `/credentials/...` is never answered, so no test can save or delete a key by accident.
    if (url.endsWith("/credentials") && (init?.method ?? "GET") === "GET") {
      const stub = credentials ?? defaultCredentials(pools);
      if (stub.kind === "network-error") return Promise.reject(new TypeError("offline"));
      if (stub.kind === "pending") return new Promise<Response>(() => undefined);
      if (stub.kind === "status") return Promise.resolve(jsonResponse(stub.body ?? {}, stub.status));
      return Promise.resolve(jsonResponse(stub.body));
    }
    // GET only, like the credentials: nothing is written to the positions route.
    if (url.endsWith("/positions/open") && (init?.method ?? "GET") === "GET") {
      const stub: OpenPositionsStub = openPositions ?? {
        kind: "ok",
        body: { as_of: "2026-10-13T12:00:00Z", positions: [], orders: [] },
      };
      if (stub.kind === "network-error") return Promise.reject(new TypeError("offline"));
      if (stub.kind === "pending") return new Promise<Response>(() => undefined);
      if (stub.kind === "status") return Promise.resolve(jsonResponse(stub.body ?? {}, stub.status));
      return Promise.resolve(jsonResponse(stub.body));
    }
    if (url.endsWith("/pools")) {
      if (pools.kind === "network-error") return Promise.reject(new TypeError("offline"));
      if (pools.kind === "pending") return new Promise<Response>(() => undefined);
      if (pools.kind === "status") return Promise.resolve(jsonResponse(pools.body ?? {}, pools.status));
      return Promise.resolve(jsonResponse(pools.body));
    }
    // GET only, like the credentials. By default a well-formed empty reading, so a shell that draws the badge
    // reads "nothing needs the owner" rather than a rejected request.
    if (url.endsWith("/reconciliation/confirmed") && (init?.method ?? "GET") === "GET") {
      const wanted: ConfirmedStub = confirmed ?? { kind: "ok", body: confirmedBody() };
      const stub: PoolsStub =
        wanted.kind === "sequence"
          ? (wanted.stubs[Math.min(confirmedRequests, wanted.stubs.length - 1)] as PoolsStub)
          : wanted;
      confirmedRequests += 1;
      if (stub.kind === "network-error") return Promise.reject(new TypeError("offline"));
      if (stub.kind === "pending") return new Promise<Response>(() => undefined);
      if (stub.kind === "status") return Promise.resolve(jsonResponse(stub.body ?? {}, stub.status));
      return Promise.resolve(jsonResponse(stub.body));
    }
    unexpected.push(url);
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
  vi.stubGlobal("fetch", fetchMock);
  return Object.assign(fetchMock, { unexpected });
}

/**
 * jsdom has no layout, so the `lg` breakpoint (1024 px) is a stubbed
 * `matchMedia`: `wide` matches `(min-width: 1024px)`, `narrow` does not.
 * `vi.unstubAllGlobals()` in `afterEach` puts it back.
 */
export function setViewport(width: "wide" | "narrow"): void {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: width === "wide",
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

/** The e-mail `GET /api/me` answers after `unlock()`. */
export const SIGNED_IN_EMAIL = "owner@example.com";

let signedIn = false;

/** `stubApi` answers `GET /api/me` with the admin, so the sign-in gate opens. */
export function unlock(): void {
  signedIn = true;
}

/**
 * `stubApi` answers `GET /api/me` with 401, so the gate stays closed. The page
 * reload a 401 triggers is replaced: jsdom cannot navigate.
 */
export function lock(): void {
  window.localStorage.clear();
  window.sessionStorage.clear();
  signedIn = false;
  vi.spyOn(page, "reload").mockImplementation(() => undefined);
}

/** Forget the exchange picked in an earlier test, in memory and in storage. */
export function resetExchangeScope(): void {
  window.localStorage.clear();
  useExchangeStore.setState({ selected: null });
}

export function renderAt(ui: ReactElement, path = "/") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}
