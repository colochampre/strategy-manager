import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { emptyPerformance, lock, pool, renderAt, resetExchangeScope, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const TWO_EXCHANGES = { kind: "ok", body: [pool("bybit", "linear"), pool("binance")] } as const;

function proposal(exchange: string, symbol: string) {
  return {
    id: `id-${symbol}`,
    discrepancy_id: "d",
    exchange,
    venue: "usdt-m",
    settlement_currency: "USDT",
    symbol,
    kind: "ATTRIBUTABLE_FULL_CLOSE",
    allocation_id: "a",
    strategy_id: "s",
    side: "SELL",
    quantity: "1",
    observed_venue_net_base: "0",
    observed_ledger_net_base: "-1",
    observed_allocation_ids: [],
    fills: [],
    client_order_id: "c",
    expires_at: "2026-09-24T01:02:03+00:00",
    prepared_by_job_id: "j",
    created_at: "2026-09-23T01:02:03+00:00",
    state: "PENDING",
    decided_at: null,
    decided_by: null,
    decision_reason: null,
    execution_attempt_id: null,
  };
}

const BOOKINGS = [proposal("bybit", "SOLUSDT.P"), proposal("binance", "ETHUSDT.P")];

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

describe("decision rail scoped to the exchange", () => {
  it("shows only the default exchange's pending bookings at first", async () => {
    stubApi(HEALTH, BOOKINGS, TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    expect(await screen.findByText("SOLUSDT.P")).toBeInTheDocument();
    expect(screen.queryByText("ETHUSDT.P")).not.toBeInTheDocument();
  });

  it("switches the rail to the other exchange when its tab is clicked", async () => {
    stubApi(HEALTH, BOOKINGS, TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");
    await screen.findByText("SOLUSDT.P");

    fireEvent.click(screen.getAllByRole("button", { name: "binance" })[0] as HTMLElement);

    expect(await screen.findByText("ETHUSDT.P")).toBeInTheDocument();
    expect(screen.queryByText("SOLUSDT.P")).not.toBeInTheDocument();
  });

  it("shows the empty state for an exchange with nothing pending", async () => {
    stubApi(HEALTH, [proposal("bybit", "SOLUSDT.P")], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");
    await screen.findByText("SOLUSDT.P");

    fireEvent.click(screen.getAllByRole("button", { name: "binance" })[0] as HTMLElement);

    expect(await screen.findByText(en.overview.decisionRail.empty)).toBeInTheDocument();
    expect(screen.queryByText("SOLUSDT.P")).not.toBeInTheDocument();
  });
});

describe("while the exchange scope is not known", () => {
  it("shows no bookings while pools load", async () => {
    stubApi(HEALTH, BOOKINGS, { kind: "pending" });
    renderAt(<AppRoutes />, "/");

    const rail = await screen.findByRole("complementary");
    expect(rail).toHaveTextContent(en.overview.decisionRail.scopeLoading);
    expect(screen.queryByText("SOLUSDT.P")).not.toBeInTheDocument();
    expect(screen.queryByText("ETHUSDT.P")).not.toBeInTheDocument();
    expect(screen.queryByText(en.overview.decisionRail.empty)).not.toBeInTheDocument();
  });

  it.each([
    ["a 500", { kind: "status", status: 500, body: { detail: "boom" } }],
    ["a network failure", { kind: "network-error" }],
    ["a malformed body", { kind: "ok", body: { items: [] } }],
  ] as const)("never shows unfiltered bookings when pools fail with %s", async (_label, stub) => {
    stubApi(HEALTH, BOOKINGS, stub);
    renderAt(<AppRoutes />, "/");

    const rail = await screen.findByRole("complementary");
    await waitFor(() => expect(rail).toHaveTextContent(en.overview.decisionRail.scopeError));
    expect(screen.queryByText("SOLUSDT.P")).not.toBeInTheDocument();
    expect(screen.queryByText("ETHUSDT.P")).not.toBeInTheDocument();
    expect(screen.queryByText(en.overview.decisionRail.empty)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: en.bookings.actions.approve })).not.toBeInTheDocument();
  });

  it("says no exchange is configured, and shows no bookings, when there are no pools", async () => {
    stubApi(HEALTH, BOOKINGS, { kind: "ok", body: [] });
    renderAt(<AppRoutes />, "/");

    const rail = await screen.findByRole("complementary");
    await waitFor(() => expect(rail).toHaveTextContent(en.overview.decisionRail.noExchanges));
    expect(screen.queryByText("SOLUSDT.P")).not.toBeInTheDocument();
    expect(screen.queryByText("ETHUSDT.P")).not.toBeInTheDocument();
  });

  it("keeps the rail heading and the page title in every state", async () => {
    stubApi(HEALTH, BOOKINGS, { kind: "network-error" });
    renderAt(<AppRoutes />, "/");

    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: en.overview.decisionRail.title })).toBeInTheDocument();
  });
});

describe("copy", () => {
  it("has the rail's scope messages in English and Spanish", () => {
    for (const locale of [en, es]) {
      expect(locale.overview.decisionRail.scopeLoading).toBeTruthy();
      expect(locale.overview.decisionRail.scopeError).toBeTruthy();
      expect(locale.overview.decisionRail.noExchanges).toBeTruthy();
    }
  });
});

// --- pool panels (tasks 8o.1 and 8o.3) ------------------------------------------------

const BALANCE = { total: "5000.00", available: "1284.52", observed_at: "2026-09-30T10:00:00+00:00", stale: false };

function ranges(pnl30: string) {
  return [
    { range: "7D", pnl: "5.00", return: "0.0100000000", trade_count: 1 },
    { range: "30D", pnl: pnl30, return: "0.0340000000", trade_count: 3 },
    { range: "90D", pnl: "77.00", return: "0.0500000000", trade_count: 6 },
    { range: "1Y", pnl: "88.00", return: "0.0600000000", trade_count: 7 },
    { range: "All", pnl: "99.00", return: "0.0700000000", trade_count: 8 },
  ];
}

/** A pool with closed trades: two curve days and one month. */
function activeReport(exchange: string, venue: string, currency: string, pnl30 = "41.20") {
  return {
    ...emptyPerformance(exchange, venue, currency),
    trade_count: 3,
    total_pnl: "99.00",
    max_drawdown: "-0.0200000000",
    ranges: ranges(pnl30),
    curve: [
      { date: "2026-09-01", daily_return: "0.0100000000", index: "1.0100000000", drawdown: "0.0000000000" },
      { date: "2026-09-02", daily_return: "0.0200000000", index: "1.0302000000", drawdown: "0.0000000000" },
    ],
    monthly: [{ year: 2026, month: 9, return: "0.0302000000" }],
  };
}

function performanceCalls(fetchMock: ReturnType<typeof stubApi>): string[] {
  return fetchMock.mock.calls.map((call) => String(call[0])).filter((url) => url.includes("/performance/"));
}

describe("one panel per pool of the exchange", () => {
  const POOLS = {
    kind: "ok",
    body: [
      pool("bybit", "linear", "USDT", BALANCE),
      pool("bybit", "inverse", "BTC", { ...BALANCE, total: "0.50000000", available: "0.12500000" }),
      pool("binance", "usdt-m", "USDT", { ...BALANCE, available: "777.00" }),
    ],
  } as const;

  it("test_renders_one_poolpanel_per_pool_never_merged_rule_7", async () => {
    const fetchMock = stubApi(HEALTH, [], POOLS, {
      "bybit/linear/USDT": { kind: "ok", body: activeReport("bybit", "linear", "USDT") },
      "bybit/inverse/BTC": { kind: "ok", body: activeReport("bybit", "inverse", "BTC") },
    });
    renderAt(<AppRoutes />, "/");

    const panels = await screen.findAllByTestId("pool-panel");
    expect(panels).toHaveLength(2);
    const [usdt, btc] = panels as [HTMLElement, HTMLElement];
    expect(within(usdt).getByTestId("pool-eyebrow")).toHaveTextContent("bybit · linear · USDT");
    expect(within(btc).getByTestId("pool-eyebrow")).toHaveTextContent("bybit · inverse · BTC");

    await waitFor(() => expect(within(usdt).getByTestId("ledger-lead")).toHaveTextContent("1,284.52"));
    await waitFor(() => expect(within(btc).getByTestId("ledger-lead")).toHaveTextContent("0.12500000"));
    expect(within(usdt).getByTestId("ledger-line")).toHaveTextContent("USDT available");
    expect(within(btc).getByTestId("ledger-line")).toHaveTextContent("BTC available");
    expect(screen.getAllByTestId("ledger-line")).toHaveLength(2);
    expect(screen.queryByText(/777/)).not.toBeInTheDocument();

    expect(performanceCalls(fetchMock).sort()).toEqual([
      expect.stringMatching(/\/performance\/pools\/bybit\/inverse\/BTC$/),
      expect.stringMatching(/\/performance\/pools\/bybit\/linear\/USDT$/),
    ]);
  });

  it("shows the other exchange's pool, and only its pool, after a tab switch", async () => {
    stubApi(HEALTH, [], POOLS);
    renderAt(<AppRoutes />, "/");
    await screen.findAllByTestId("pool-panel");

    fireEvent.click(screen.getAllByRole("button", { name: "binance" })[0] as HTMLElement);

    await waitFor(() => expect(screen.getAllByTestId("pool-panel")).toHaveLength(1));
    expect(screen.getByTestId("pool-eyebrow")).toHaveTextContent("binance · usdt-m · USDT");
    await waitFor(() => expect(screen.getByTestId("ledger-lead")).toHaveTextContent("777.00"));
  });

  it("requests no report and shows no panel until the exchange is known", async () => {
    const fetchMock = stubApi(HEALTH, [], { kind: "pending" });
    renderAt(<AppRoutes />, "/");
    await screen.findByRole("complementary");

    expect(screen.queryByTestId("pool-panel")).not.toBeInTheDocument();
    expect(performanceCalls(fetchMock)).toEqual([]);
  });

  it("requests no report and shows no panel when the pools failed", async () => {
    const fetchMock = stubApi(HEALTH, [], { kind: "status", status: 500, body: { detail: "boom" } });
    renderAt(<AppRoutes />, "/");
    const rail = await screen.findByRole("complementary");
    await waitFor(() => expect(rail).toHaveTextContent(en.overview.decisionRail.scopeError));

    expect(screen.queryByTestId("pool-panel")).not.toBeInTheDocument();
    expect(performanceCalls(fetchMock)).toEqual([]);
  });
});

describe("the empty states", () => {
  it("test_empty_ledger_dry_run_shows_defined_empty_states_no_error", async () => {
    stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit", "linear", "USDT", BALANCE)] });
    renderAt(<AppRoutes />, "/");

    expect(await screen.findByText(en.overview.returnChart.empty)).toBeInTheDocument();
    expect(screen.getByText(en.overview.monthlyGrid.empty)).toBeInTheDocument();
    expect(screen.getByTestId("ledger-lead")).toHaveTextContent("1,284.52");
    expect(screen.getByTestId("ledger-pnl")).toHaveTextContent("0.00");
    expect(screen.getByTestId("ledger-return")).toHaveTextContent("0.0%");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(en.overview.pool.error)).not.toBeInTheDocument();
  });

  it("reads a 404 as a pool without a report, never as an error", async () => {
    stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit", "linear", "USDT", BALANCE)] }, {
      "bybit/linear/USDT": { kind: "status", status: 404, body: { detail: "no such pool" } },
    });
    renderAt(<AppRoutes />, "/");

    const panel = await screen.findByTestId("pool-panel");
    expect(await within(panel).findByText(en.overview.pool.noReport)).toBeInTheDocument();
    expect(within(panel).getByTestId("pool-eyebrow")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says a panel is loading while its report is on the way", async () => {
    stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit", "linear", "USDT", BALANCE)] }, {
      "bybit/linear/USDT": { kind: "pending" },
    });
    renderAt(<AppRoutes />, "/");

    const panel = await screen.findByTestId("pool-panel");
    expect(await within(panel).findByText(en.overview.pool.loading)).toBeInTheDocument();
    expect(within(panel).getByTestId("pool-eyebrow")).toBeInTheDocument();
    expect(within(panel).queryByTestId("ledger-line")).not.toBeInTheDocument();
    expect(screen.queryByText(en.overview.returnChart.empty)).not.toBeInTheDocument();
  });
});

describe("one pool failing", () => {
  const TWO = {
    kind: "ok",
    body: [pool("bybit", "linear", "USDT", BALANCE), pool("bybit", "inverse", "BTC", BALANCE)],
  } as const;

  it.each([
    ["a 500", { kind: "status", status: 500, body: { detail: "boom" } }],
    ["a network failure", { kind: "network-error" }],
    ["a malformed body", { kind: "ok", body: { items: [] } }],
  ] as const)("blanks only its own panel, with %s", async (_label, failure) => {
    stubApi(HEALTH, [], TWO, {
      "bybit/linear/USDT": failure,
      "bybit/inverse/BTC": { kind: "ok", body: activeReport("bybit", "inverse", "BTC") },
    });
    renderAt(<AppRoutes />, "/");

    const [failed, healthy] = (await screen.findAllByTestId("pool-panel")) as [HTMLElement, HTMLElement];
    expect(await within(failed).findByRole("alert")).toHaveTextContent(en.overview.pool.error);
    expect(within(failed).queryByText(en.overview.returnChart.empty)).not.toBeInTheDocument();
    expect(await within(healthy).findByTestId("ledger-line")).toBeInTheDocument();
    expect(within(healthy).queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("complementary")).toBeInTheDocument();
  });
});

describe("the available balance", () => {
  it("comes from the pools row's balance.available, not its total or allocatable", async () => {
    stubApi(HEALTH, [], {
      kind: "ok",
      body: [
        {
          ...pool("bybit", "linear", "USDT", { ...BALANCE, total: "9999.00", available: "1284.52" }),
          allocatable: "555.55",
          reserved: "729.00",
        },
      ],
    });
    renderAt(<AppRoutes />, "/");

    await waitFor(() => expect(screen.getByTestId("ledger-lead")).toHaveTextContent("1,284.52"));
    expect(screen.getByTestId("ledger-lead")).not.toHaveTextContent("9,999.00");
    expect(screen.getByTestId("ledger-lead")).not.toHaveTextContent("555.55");
  });

  it("is an em dash, not zero, for a pool nothing has synced", async () => {
    stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit", "linear")] });
    renderAt(<AppRoutes />, "/");

    await waitFor(() => expect(screen.getByTestId("ledger-lead")).toHaveTextContent("—"));
    expect(screen.queryByTestId("balance-stale")).not.toBeInTheDocument();
  });

  it("is flagged when the snapshot is stale, in a neutral colour", async () => {
    stubApi(HEALTH, [], {
      kind: "ok",
      body: [pool("bybit", "linear", "USDT", { ...BALANCE, stale: true })],
    });
    renderAt(<AppRoutes />, "/");

    const note = await screen.findByTestId("balance-stale");
    expect(note).toHaveTextContent("Balance is out of date: last synced");
    expect(note).toHaveTextContent("2026");
    expect(note.className).not.toContain("text-decision");
    await waitFor(() => expect(screen.getByTestId("ledger-lead")).toHaveTextContent("1,284.52"));
  });

  it("carries no stale flag for a fresh snapshot", async () => {
    stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit", "linear", "USDT", BALANCE)] });
    renderAt(<AppRoutes />, "/");

    await screen.findByTestId("ledger-lead");
    expect(screen.queryByTestId("balance-stale")).not.toBeInTheDocument();
  });
});

describe("the range selector", () => {
  const TWO = {
    kind: "ok",
    body: [pool("bybit", "linear", "USDT", BALANCE), pool("bybit", "inverse", "BTC", BALANCE)],
  } as const;

  it("only picks an entry of ranges[]: no second report request", async () => {
    const fetchMock = stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit", "linear", "USDT", BALANCE)] }, {
      "bybit/linear/USDT": { kind: "ok", body: activeReport("bybit", "linear", "USDT") },
    });
    renderAt(<AppRoutes />, "/");
    await waitFor(() => expect(screen.getByTestId("ledger-pnl")).toHaveTextContent("+41.20"));

    fireEvent.click(screen.getByRole("button", { name: "7D" }));

    await waitFor(() => expect(screen.getByTestId("ledger-pnl")).toHaveTextContent("+5.00"));
    expect(screen.getByTestId("ledger-return")).toHaveTextContent("+1.0%");
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    await waitFor(() => expect(screen.getByTestId("ledger-pnl")).toHaveTextContent("+99.00"));
    expect(performanceCalls(fetchMock)).toHaveLength(1);
  });

  it("belongs to its own panel: pressing 7D on one leaves the other on 30D", async () => {
    stubApi(HEALTH, [], TWO, {
      "bybit/linear/USDT": { kind: "ok", body: activeReport("bybit", "linear", "USDT") },
      "bybit/inverse/BTC": { kind: "ok", body: activeReport("bybit", "inverse", "BTC", "0.41200000") },
    });
    renderAt(<AppRoutes />, "/");
    const [first, second] = (await screen.findAllByTestId("pool-panel")) as [HTMLElement, HTMLElement];
    await waitFor(() => expect(within(second).getByTestId("ledger-pnl")).toBeInTheDocument());
    await waitFor(() => expect(within(first).getByTestId("ledger-pnl")).toBeInTheDocument());

    fireEvent.click(within(first).getByRole("button", { name: "7D" }));

    await waitFor(() => expect(within(first).getByTestId("ledger-pnl")).toHaveTextContent("+5.00"));
    expect(within(second).getByRole("button", { name: "30D" })).toHaveAttribute("aria-pressed", "true");
    expect(within(second).getByTestId("ledger-pnl")).toHaveTextContent("+0.41200000");
  });
});

// --- the chart follows the range (decision 33) -----------------------------------------

const NOW = "2026-09-30T12:00:00.000Z";
const DAY_MS = 86_400_000;
const RANGE_DAYS = { "7D": 7, "30D": 30, "90D": 90, "1Y": 365, All: null } as const;
type ConsistentRange = keyof typeof RANGE_DAYS;

function utcDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/**
 * A report whose `ranges[]` agree with its `curve` by construction: a closed day
 * every 4th day, each range compounded from the daily returns of the days on or
 * after its start day (the server compounds the trades inside its window, and
 * none of these days straddles a window edge). The curve's index and drawdown
 * are compounded independently from the same daily returns.
 */
function consistentReport(exchange: string, venue: string, currency: string) {
  const now = Date.parse(NOW);
  const days: Array<{ date: string; r: number }> = [];
  for (let back = 400, i = 0; back >= 0; back -= 4, i += 1) {
    days.push({ date: utcDate(now - back * DAY_MS), r: ((i * 37) % 11 - 5) / 200 });
  }
  let index = 1;
  let peak = 1;
  const curve = days.map(({ date, r }) => {
    index *= 1 + r;
    peak = Math.max(peak, index);
    return {
      date,
      daily_return: r.toFixed(10),
      index: index.toFixed(10),
      drawdown: (index / peak - 1).toFixed(10),
    };
  });
  const ranges = Object.entries(RANGE_DAYS).map(([range, length]) => {
    const from = length === null ? "" : utcDate(now - length * DAY_MS);
    const inside = days.filter((day) => day.date >= from);
    return {
      range,
      pnl: "1.00",
      return: (inside.reduce((acc, day) => acc * (1 + day.r), 1) - 1).toFixed(10),
      trade_count: inside.length,
    };
  });
  return {
    ...emptyPerformance(exchange, venue, currency),
    trade_count: days.length,
    max_drawdown: "-0.0500000000",
    ranges,
    curve,
    monthly: [{ year: 2026, month: 9, return: "0.0100000000" }],
  };
}

/** How many curve days a 30D window holds in that report (the default range). */
const CONSISTENT_DAYS_30D = 8;

function chartDays(scope: HTMLElement): number {
  const curve = within(scope).queryByTestId("return-curve");
  return curve === null ? 0 : (curve.getAttribute("d") ?? "").split("L").length;
}

function finalReturn(scope: HTMLElement): number {
  return Number(within(scope).getByTestId("return-curve").getAttribute("data-final-return"));
}

describe("the month grid keeps the whole history behind its three years", () => {
  it("summarises every month, and shows three year rows with the rest behind a toggle", async () => {
    const report = {
      ...activeReport("bybit", "linear", "USDT"),
      monthly: [
        { year: 2022, month: 6, return: "-0.0500000000" },
        { year: 2023, month: 1, return: "0.0200000000" },
        { year: 2024, month: 1, return: "0.0100000000" },
        { year: 2025, month: 1, return: "0.0100000000" },
        { year: 2026, month: 1, return: "0.0300000000" },
      ],
    };
    stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit", "linear", "USDT", BALANCE)] }, {
      "bybit/linear/USDT": { kind: "ok", body: report },
    });
    renderAt(<AppRoutes />, "/");
    const panel = await screen.findByTestId("pool-panel");

    const summary = await within(panel).findByTestId("monthly-summary");
    // 4 of 5 months are positive: the summary reads 2022 and 2023 too.
    expect(summary).toHaveTextContent("4 of 5 months positive");
    expect(summary).toHaveTextContent("worst -5.0%");
    expect(within(panel).getAllByRole("rowheader").map((node) => node.textContent)).toEqual(["2026", "2025", "2024"]);

    fireEvent.click(within(panel).getByRole("button", { name: "Show earlier years" }));
    expect(within(panel).getAllByRole("rowheader")).toHaveLength(5);
  });
});

describe("the chart follows the selected range", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(NOW));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  const ONE = { kind: "ok", body: [pool("bybit", "linear", "USDT", BALANCE)] } as const;

  it("starts on the same range as the ledger line: 30D", async () => {
    stubApi(HEALTH, [], ONE, { "bybit/linear/USDT": { kind: "ok", body: consistentReport("bybit", "linear", "USDT") } });
    renderAt(<AppRoutes />, "/");
    const panel = await screen.findByTestId("pool-panel");
    await within(panel).findByTestId("return-curve");

    expect(within(panel).getByRole("button", { name: "30D" })).toHaveAttribute("aria-pressed", "true");
    expect(chartDays(panel)).toBe(CONSISTENT_DAYS_30D);
  });

  it.each(Object.keys(RANGE_DAYS) as ConsistentRange[])(
    "ends %s on the ledger line's return for the same range",
    async (range) => {
      const report = consistentReport("bybit", "linear", "USDT");
      stubApi(HEALTH, [], ONE, { "bybit/linear/USDT": { kind: "ok", body: report } });
      renderAt(<AppRoutes />, "/");
      const panel = await screen.findByTestId("pool-panel");
      await within(panel).findByTestId("return-curve");

      fireEvent.click(within(panel).getByRole("button", { name: range }));

      const expected = Number(report.ranges.find((entry) => entry.range === range)?.return);
      await waitFor(() => expect(finalReturn(panel)).toBeCloseTo(expected, 8));
    },
  );

  it("draws a shorter window with fewer days than a longer one", async () => {
    stubApi(HEALTH, [], ONE, { "bybit/linear/USDT": { kind: "ok", body: consistentReport("bybit", "linear", "USDT") } });
    renderAt(<AppRoutes />, "/");
    const panel = await screen.findByTestId("pool-panel");
    await within(panel).findByTestId("return-curve");

    const counts: number[] = [];
    for (const range of ["7D", "30D", "90D", "1Y", "All"]) {
      fireEvent.click(within(panel).getByRole("button", { name: range }));
      await waitFor(() => expect(within(panel).getByRole("button", { name: range })).toHaveAttribute("aria-pressed", "true"));
      counts.push(chartDays(panel));
    }
    expect(counts).toEqual([2, 8, 23, 92, 101]);
  });

  it("belongs to its own panel: 7D on one redraws only that chart", async () => {
    const two = {
      kind: "ok",
      body: [pool("bybit", "linear", "USDT", BALANCE), pool("bybit", "inverse", "BTC", BALANCE)],
    } as const;
    stubApi(HEALTH, [], two, {
      "bybit/linear/USDT": { kind: "ok", body: consistentReport("bybit", "linear", "USDT") },
      "bybit/inverse/BTC": { kind: "ok", body: consistentReport("bybit", "inverse", "BTC") },
    });
    renderAt(<AppRoutes />, "/");
    const [first, second] = (await screen.findAllByTestId("pool-panel")) as [HTMLElement, HTMLElement];
    await within(first).findByTestId("return-curve");
    await within(second).findByTestId("return-curve");

    fireEvent.click(within(first).getByRole("button", { name: "7D" }));

    await waitFor(() => expect(chartDays(first)).toBe(2));
    expect(chartDays(second)).toBe(CONSISTENT_DAYS_30D);
  });

  it("shows the empty-range state, no error, when the window holds no day", async () => {
    const report = consistentReport("bybit", "linear", "USDT");
    const quiet = { ...report, curve: report.curve.slice(0, 50) };
    stubApi(HEALTH, [], ONE, { "bybit/linear/USDT": { kind: "ok", body: quiet } });
    renderAt(<AppRoutes />, "/");
    const panel = await screen.findByTestId("pool-panel");

    expect(await within(panel).findByText(en.overview.returnChart.emptyRange)).toBeInTheDocument();
    expect(within(panel).queryByTestId("return-curve")).toBeNull();
    expect(within(panel).queryByRole("alert")).toBeNull();
    fireEvent.click(within(panel).getByRole("button", { name: "All" }));
    await waitFor(() => expect(within(panel).getByTestId("return-curve")).toBeInTheDocument());
    expect(within(panel).queryByText(en.overview.returnChart.emptyRange)).toBeNull();
  });
});

describe("copy", () => {
  it("has the pool panel's messages in English and Spanish", () => {
    for (const locale of [en, es]) {
      expect(locale.overview.pool.loading).toBeTruthy();
      expect(locale.overview.pool.error).toBeTruthy();
      expect(locale.overview.pool.noReport).toBeTruthy();
      expect(locale.overview.pool.stale).toContain("{{time}}");
    }
  });
});
