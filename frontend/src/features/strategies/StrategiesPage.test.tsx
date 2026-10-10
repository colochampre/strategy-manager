import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import {
  emptyPerformance,
  jsonResponse,
  lock,
  pool,
  renderAt,
  resetExchangeScope,
  stubApi,
  unlock,
} from "@/test/harness";
import type { ExtraRoute } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const POOLS = { kind: "ok", body: [pool("bybit", "usdt-m"), pool("binance", "usdt-m")] } as const;

const DAY_S = 86_400;

function strategy(overrides: Record<string, unknown> = {}) {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    name: "Alpha",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    allocation_percent: "100",
    enabled: true,
    archived_at: null,
    allowed_pairs: ["SOLUSDT"],
    uptime: { seconds: 12 * DAY_S + 3600, first_enabled_at: "2026-09-18T10:00:00Z", baseline: false },
    ...overrides,
  };
}

const ARCHIVED = strategy({
  id: "22222222-2222-4222-8222-222222222222",
  name: "Old Beta",
  enabled: false,
  archived_at: "2026-09-01T00:00:00Z",
});

/** What `GET /performance/strategies/{id}` answers for a strategy with seven closed trades. */
function strategyReport(id: string) {
  const all = { range: "All", pnl: "41.20", return: "0.0340000000", trade_count: 7 };
  const base = emptyPerformance("bybit", "usdt-m", "USDT");
  return {
    ...base,
    strategy_id: id,
    by_pair: [],
    trade_count: 7,
    total_pnl: "41.20",
    ranges: [...base.ranges.filter((entry) => entry.range !== "All"), all],
  };
}

interface StrategiesApi {
  rows: unknown[];
  route: ExtraRoute;
  calls: Array<{ method: string; url: string; body: unknown }>;
}

/** A backend double: lists honour `include_archived`, PATCH answers the updated row. */
function strategiesApi(rows: Array<ReturnType<typeof strategy>>, perf?: ExtraRoute): StrategiesApi {
  const calls: StrategiesApi["calls"] = [];
  const route: ExtraRoute = (url, init) => {
    const parsed = new URL(url, "http://localhost");
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
    const performance = /\/performance\/strategies\/([^/]+)$/.exec(parsed.pathname);
    if (performance !== null) {
      return perf?.(url, init) ?? Promise.resolve(jsonResponse(strategyReport(performance[1] ?? "")));
    }
    if (!/\/strategies(\/[^/]+)?$/.test(parsed.pathname)) return undefined;
    calls.push({ method, url, body });
    if (method === "PATCH") {
      const id = parsed.pathname.split("/").pop();
      const row = rows.find((candidate) => candidate.id === id);
      return Promise.resolve(jsonResponse({ ...row, ...(body as object) }));
    }
    const includeArchived = parsed.searchParams.get("include_archived") === "true";
    return Promise.resolve(jsonResponse(rows.filter((row) => includeArchived || row.archived_at === null)));
  };
  return { rows, route, calls };
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

describe("the strategies list", () => {
  it("test_archived_excluded_by_default_toggle_shows_them", async () => {
    const api = strategiesApi([strategy(), ARCHIVED]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");

    expect(await screen.findByText("Alpha")).toBeInTheDocument();
    expect(screen.queryByText("Old Beta")).not.toBeInTheDocument();
    expect(api.calls[0]?.url).not.toContain("include_archived=true");

    fireEvent.click(screen.getByRole("checkbox", { name: en.strategies.archivedToggle }));

    expect(await screen.findByText("Old Beta")).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(api.calls.at(-1)?.url).toContain("include_archived=true");
    const archivedRow = screen.getByText("Old Beta").closest("[data-testid='strategy-row']") as HTMLElement;
    expect(within(archivedRow).getByText(en.strategies.row.archived)).toBeInTheDocument();
    expect(within(archivedRow).getByRole("switch")).toBeDisabled();

    fireEvent.click(screen.getByRole("checkbox", { name: en.strategies.archivedToggle }));
    await waitFor(() => expect(screen.queryByText("Old Beta")).not.toBeInTheDocument());
  });

  it("test_row_shows_name_pool_enabled_toggle_uptime_trades_pnl_return", async () => {
    const api = strategiesApi([strategy({ allowed_pairs: ["ETHUSDT", "BTCUSDT"] })]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");

    const row = await screen.findByTestId("strategy-row");
    expect(within(row).getByRole("link", { name: "Alpha" })).toHaveAttribute(
      "href",
      "/strategies/11111111-1111-4111-8111-111111111111",
    );
    // Decision 39: the venue and the allowed pairs, in the API's order. The exchange
    // (the operator is on its tab) and the settlement currency (shown by the PnL) are not repeated.
    const subLine = within(row).getByTestId("strategy-pool");
    expect(subLine.textContent).toBe("usdt-m · ETHUSDT, BTCUSDT");
    expect(subLine).not.toHaveTextContent("bybit");
    expect(subLine.textContent).not.toMatch(/\bUSDT\b/);
    expect(within(row).getByRole("switch", { name: "Enable Alpha" })).toHaveAttribute("aria-checked", "true");
    expect(within(row).getByTestId("strategy-uptime")).toHaveTextContent("active 12 days");
    await waitFor(() => expect(within(row).getByTestId("strategy-trades")).toHaveTextContent("7"));
    expect(within(row).getByTestId("strategy-pnl")).toHaveTextContent("+41.20 USDT");
    expect(within(row).getByTestId("strategy-return")).toHaveTextContent("+3.4%");
  });

  it("test_the_strategies_list_shows_no_rows_share", async () => {
    const api = strategiesApi([strategy({ allocation_percent: "37.5" })]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");

    const row = await screen.findByTestId("strategy-row");
    await waitFor(() => expect(within(row).getByTestId("strategy-trades")).toHaveTextContent("7"));
    expect(row.textContent).not.toContain("37.5");
    expect(row.textContent?.toLowerCase()).not.toContain("per trade");
    expect(row.textContent).not.toContain(en.strategies.detail.share.label);
    expect(within(row).queryByRole("slider")).toBeNull();
  });

  it("shows the venue alone, with no trailing separator, when a strategy has no allowed pairs", async () => {
    const api = strategiesApi([strategy({ allowed_pairs: [] })]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");

    const row = await screen.findByTestId("strategy-row");
    expect(within(row).getByTestId("strategy-pool").textContent).toBe("usdt-m");
  });

  it("shows a never-enabled strategy as off, with no activation claim", async () => {
    const never = strategy({
      enabled: false,
      uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    });
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([never]).route);
    renderAt(<AppRoutes />, "/strategies");

    const row = await screen.findByTestId("strategy-row");
    expect(within(row).getByRole("switch")).toHaveAttribute("aria-checked", "false");
    expect(within(row).getByTestId("strategy-uptime")).toHaveTextContent(en.strategies.row.neverEnabled);
  });

  it("says 'at least' when the first activation is only a baseline", async () => {
    const baseline = strategy({ uptime: { seconds: 3 * DAY_S, first_enabled_at: "2026-09-29T00:00:00Z", baseline: true } });
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([baseline]).route);
    renderAt(<AppRoutes />, "/strategies");

    expect(await screen.findByTestId("strategy-uptime")).toHaveTextContent("active at least 3 days");
  });

  it("lists only the selected exchange's strategies, and follows a tab switch", async () => {
    const other = strategy({ id: "33333333-3333-4333-8333-333333333333", name: "Gamma", exchange: "binance", venue: "usdt-m" });
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy(), other]).route);
    renderAt(<AppRoutes />, "/strategies");

    expect(await screen.findByText("Alpha")).toBeInTheDocument();
    expect(screen.queryByText("Gamma")).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "binance" })[0] as HTMLElement);

    expect(await screen.findByText("Gamma")).toBeInTheDocument();
    expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
  });

  it("says so when the exchange has no strategies", async () => {
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([]).route);
    renderAt(<AppRoutes />, "/strategies");

    expect(await screen.findByText(en.strategies.empty)).toBeInTheDocument();
  });

  it("shows a failed list as an error, never as an empty list", async () => {
    stubApi(HEALTH, [], POOLS, {}, (url) =>
      /\/strategies(\?|$)/.test(url) ? Promise.resolve(jsonResponse({ detail: "boom" }, 500)) : undefined,
    );
    renderAt(<AppRoutes />, "/strategies");

    expect(await screen.findByRole("alert")).toHaveTextContent(en.strategies.error);
    expect(screen.queryByText(en.strategies.empty)).not.toBeInTheDocument();
  });

  it("shows a malformed list body as an error", async () => {
    stubApi(HEALTH, [], POOLS, {}, (url) =>
      /\/strategies(\?|$)/.test(url) ? Promise.resolve(jsonResponse({ items: [] })) : undefined,
    );
    renderAt(<AppRoutes />, "/strategies");

    expect(await screen.findByRole("alert")).toHaveTextContent(en.strategies.error);
  });

  it("shows no strategy until the exchange scope is known", async () => {
    const api = strategiesApi([strategy()]);
    stubApi(HEALTH, [], { kind: "pending" }, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");

    expect(await screen.findByText(en.strategies.scopeLoading)).toBeInTheDocument();
    expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
  });

  it("blanks only a row's figures when its report fails, and says so", async () => {
    const api = strategiesApi([strategy()], () => Promise.resolve(jsonResponse({ detail: "boom" }, 500)));
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");

    const row = await screen.findByTestId("strategy-row");
    expect(await within(row).findByText(en.strategies.row.performanceError)).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "Alpha" })).toBeInTheDocument();
  });

  it("a report without the win fields makes the row's figures unreadable", async () => {
    const olderApi = () =>
      Promise.resolve(
        jsonResponse({
          ...strategyReport("11111111-1111-4111-8111-111111111111"),
          by_pair: [{ pair: "SOLUSDT", trades: 7, pnl: "41.20", return: "0.0340000000" }],
        }),
      );
    const api = strategiesApi([strategy()], olderApi);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");

    const row = await screen.findByTestId("strategy-row");
    expect(await within(row).findByText(en.strategies.row.performanceError)).toBeInTheDocument();
    expect(within(row).queryByTestId("strategy-pnl")).not.toBeInTheDocument();
  });
});

describe("the enable switch", () => {
  it("sends the opposite value and shows the answer", async () => {
    const api = strategiesApi([strategy()]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    const row = await screen.findByTestId("strategy-row");

    fireEvent.click(within(row).getByRole("switch"));

    await waitFor(() =>
      expect(api.calls.find((call) => call.method === "PATCH")).toMatchObject({ body: { enabled: false } }),
    );
    expect(api.calls.find((call) => call.method === "PATCH")?.url).toMatch(/\/strategies\/11111111-/);
  });

  it("shows a refused change instead of swallowing it", async () => {
    const api = strategiesApi([strategy()]);
    stubApi(HEALTH, [], POOLS, {}, (url, init) =>
      init?.method === "PATCH" ? Promise.resolve(jsonResponse({ detail: "no" }, 409)) : api.route(url, init),
    );
    renderAt(<AppRoutes />, "/strategies");
    const row = await screen.findByTestId("strategy-row");

    fireEvent.click(within(row).getByRole("switch"));

    expect(await within(row).findByRole("alert")).toHaveTextContent(en.strategies.row.toggleError);
  });
});

/** The class tokens of an element, so a test names a class and not a substring of the whole attribute. */
const classesOf = (element: Element) => element.className.split(/\s+/);

describe("the list's figures line up from row to row (12f.10.30b)", () => {
  const WIDE = strategy({ id: "44444444-4444-4444-8444-444444444444", name: "Wide" });
  const NARROW = strategy({ id: "55555555-5555-4555-8555-555555555555", name: "Narrow" });

  /** Two rows whose PnL differs in width: `+1235.25` against `+988.80`, the case the owner saw. */
  async function twoRows() {
    const api = strategiesApi([WIDE, NARROW], (url) => {
      const id = /\/performance\/strategies\/([^/]+)$/.exec(url)?.[1] ?? "";
      const report = strategyReport(id);
      const pnl = id === WIDE.id ? "1235.25" : "988.80";
      const all = { range: "All", pnl, return: "0.0340000000", trade_count: 7 };
      return Promise.resolve(
        jsonResponse({ ...report, ranges: [...report.ranges.filter((entry) => entry.range !== "All"), all] }),
      );
    });
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    const rows = await screen.findAllByTestId("strategy-row");
    await waitFor(() => expect(within(rows[0] as HTMLElement).getByTestId("strategy-pnl")).toHaveTextContent("+1,235.25"));
    await waitFor(() => expect(within(rows[1] as HTMLElement).getByTestId("strategy-pnl")).toHaveTextContent("+988.80"));
    return rows;
  }

  it("the list is ONE grid of five tracks that the rows share", async () => {
    const rows = await twoRows();
    const list = (rows[0] as HTMLElement).parentElement as HTMLElement;

    expect(classesOf(list)).toEqual(
      expect.arrayContaining(["lg:grid", "lg:grid-cols-[minmax(0,1fr)_auto_auto_auto_auto]"]),
    );
  });

  it("every row takes the shared tracks on a subgrid and declares no tracks of its own", async () => {
    const rows = await twoRows();

    expect(rows).toHaveLength(2);
    for (const row of rows) {
      expect(classesOf(row)).toEqual(expect.arrayContaining(["lg:grid", "lg:grid-cols-subgrid", "lg:col-span-5"]));
      expect(classesOf(row).filter((name) => /grid-cols-\[/.test(name))).toEqual([]);
    }
  });

  it("the three figures sit on the three middle tracks of that subgrid, in every row", async () => {
    const rows = await twoRows();

    for (const row of rows) {
      const figures = within(row).getByTestId("strategy-trades").closest("dl") as HTMLElement;
      expect(classesOf(figures)).toEqual(
        expect.arrayContaining(["lg:grid", "lg:grid-cols-subgrid", "lg:col-span-3"]),
      );
      expect(classesOf(figures).filter((name) => /grid-cols-\[/.test(name))).toEqual([]);
      expect(within(figures).getAllByRole("term")).toHaveLength(3);
    }
  });

  it("a row whose report failed keeps the same three tracks for its message", async () => {
    const api = strategiesApi([strategy()], () => Promise.resolve(jsonResponse({ detail: "boom" }, 500)));
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");

    const row = await screen.findByTestId("strategy-row");
    const message = await within(row).findByText(en.strategies.row.performanceError);

    expect(classesOf(message)).toContain("lg:col-span-3");
  });

  it("a row whose report is unreadable keeps the same three tracks for its message", async () => {
    const unreadable = () =>
      Promise.resolve(
        jsonResponse({
          ...strategyReport("11111111-1111-4111-8111-111111111111"),
          by_pair: [{ pair: "SOLUSDT", trades: 7, pnl: "41.20", return: "0.0340000000" }],
        }),
      );
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy()], unreadable).route);
    renderAt(<AppRoutes />, "/strategies");

    const row = await screen.findByTestId("strategy-row");
    const message = await within(row).findByText(en.strategies.row.performanceError);

    expect(classesOf(message)).toContain("lg:col-span-3");
  });

  it("the reading order of a row is still name, figures, switch", async () => {
    const rows = await twoRows();

    for (const row of rows) {
      const link = within(row).getByRole("link");
      const figures = within(row).getByTestId("strategy-trades").closest("dl") as HTMLElement;
      const toggle = within(row).getByRole("switch");
      expect(link.compareDocumentPosition(figures) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
      expect(figures.compareDocumentPosition(toggle) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    }
  });
});

describe("copy", () => {
  it("has the list's messages in English and Spanish", () => {
    for (const locale of [en, es]) {
      expect(locale.strategies.archivedToggle).toBeTruthy();
      expect(locale.strategies.empty).toBeTruthy();
      expect(locale.strategies.loading).toBeTruthy();
      expect(locale.strategies.noExchanges).toBeTruthy();
      expect(locale.strategies.error).toBeTruthy();
      expect(locale.strategies.scopeLoading).toBeTruthy();
      expect(locale.strategies.scopeError).toBeTruthy();
      expect(locale.strategies.row.archived).toBeTruthy();
      expect(locale.strategies.row.neverEnabled).toBeTruthy();
      expect(locale.strategies.row.toggleError).toBeTruthy();
      expect(locale.strategies.row.performanceError).toBeTruthy();
      expect(locale.strategies.row.active_other).toContain("{{count}}");
      expect(locale.strategies.row.activeAtLeast_other).toContain("{{count}}");
    }
  });
});
