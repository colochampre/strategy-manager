import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { emptyPerformance, lock, pool, renderAt, resetExchangeScope, setViewport, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
/** The return chart's name: the ledger's icons are images too, so a bare `img` query meets several. */
const CHART_NAME = en.overview.returnChart.ariaLabel;
const TWO_EXCHANGES = { kind: "ok", body: [pool("bybit", "linear"), pool("binance")] } as const;

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

/** The page's own content: the shell's exchange buttons say "Loading exchanges…" too, so a message is looked for inside the page's own column. */
async function inPage() {
  return within((await title()).parentElement as HTMLElement);
}

/** The page's header (breadcrumb, title, subtitle), asserted to exist before it is returned: the messages come right under it. */
async function title(): Promise<HTMLElement> {
  const heading = await screen.findByRole("heading", { level: 1, name: /^(Overview|Panel de control)$/ });
  return heading.closest("header") as HTMLElement;
}

describe("the Overview has no decision rail (spec: no rail, on any width; prototype example 12)", () => {
  it.each([["wide"], ["narrow"]] as const)("draws no rail, no slot and no column beside the panels on a %s viewport", async (width) => {
    setViewport(width);
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    await screen.findAllByTestId("pool-panel");
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    expect(screen.queryByTestId("rail-slot")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /decision/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/pending/i)).not.toBeInTheDocument();
    expect(screen.getByTestId("overview-layout").className).not.toMatch(/xl:flex-row/);
  });

  it.each([["wide"], ["narrow"]] as const)(
    "puts nothing between the return chart and the month grid on a %s viewport",
    async (width) => {
      setViewport(width);
      stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit", "linear", "USDT", BALANCE)] }, {
        "bybit/linear/USDT": { kind: "ok", body: activeReport("bybit", "linear", "USDT") },
      });
      renderAt(<AppRoutes />, "/");

      const panel = await screen.findByTestId("pool-panel");
      const grid = await within(panel).findByTestId("month-2026-9");
      const figure = within(panel).getByRole("img", { name: CHART_NAME }).closest("figure") as HTMLElement;
      // RD.3: the chart's card is followed directly by the month grid's own card.
      const chartCard = figure.closest("section") as HTMLElement;
      expect(chartCard.nextElementSibling).toContainElement(grid);
      expect(chartCard.nextElementSibling?.tagName).toBe("SECTION");
    },
  );

  // RD.3 replaces "frames the chart, Month by month and Open positions, and not the ledger line" (owner decision 67
  // Q4, Q7): the dashboard's blocks are cards now, one each, under the header card.
  it("draws the header card, then the chart, the month grid and the open positions, each in a card of its own (ex1)", async () => {
    setViewport("wide");
    stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit", "linear", "USDT", BALANCE)] }, {
      "bybit/linear/USDT": { kind: "ok", body: activeReport("bybit", "linear", "USDT") },
    });
    renderAt(<AppRoutes />, "/");

    const panel = await screen.findByTestId("pool-panel");
    await within(panel).findByTestId("month-2026-9");
    const cards = Array.from(panel.children);
    expect(cards.map((card) => card.getAttribute("data-testid") ?? card.querySelector("h2")?.textContent)).toEqual([
      "header-card",
      "Compounded return",
      "Monthly performance",
      "Open positions",
    ]);
    expect(within(panel).queryByTestId("report-section")).toBeNull();
  });
});

describe("the Overview carries its own scope messages (spec; prototype example 13; design K row 7)", () => {
  const MESSAGES = {
    en: {
      loading: "Loading exchanges…",
      error: "The pools are hidden because the exchanges could not be loaded, so they cannot be filtered.",
      none: "No exchange is configured, so there are no pools to show.",
      title: "Overview",
    },
    es: {
      loading: "Cargando exchanges…",
      error: "Los pools están ocultos porque no se pudieron cargar los exchanges y no se pueden filtrar.",
      none: "No hay ningún exchange configurado, por lo que no hay pools que mostrar.",
      title: "Panel de control",
    },
  } as const;

  it.each([["en"], ["es"]] as const)("draws the loading message as a status in ink-3, under the title, in %s", async (language) => {
    await act(() => i18n.changeLanguage(language));
    stubApi(HEALTH, [], { kind: "pending" });
    renderAt(<AppRoutes />, "/");

    const message = await (await inPage()).findByText(MESSAGES[language].loading);
    expect(message).toHaveAttribute("role", "status");
    expect(message).toHaveClass("text-ink-3");
    expect(message.previousElementSibling).toBe(await title());
    expect(screen.queryByTestId("pool-panel")).not.toBeInTheDocument();
  });

  it.each([
    ["en", "a 500", { kind: "status", status: 500, body: { detail: "boom" } }],
    ["es", "a network failure", { kind: "network-error" }],
    ["en", "a malformed body", { kind: "ok", body: { items: [] } }],
  ] as const)("draws the failed message as an alert in a red-bordered box, in %s, for %s", async (language, _label, stub) => {
    await act(() => i18n.changeLanguage(language));
    stubApi(HEALTH, [], stub);
    renderAt(<AppRoutes />, "/");

    const message = await (await inPage()).findByText(MESSAGES[language].error);
    expect(message).toHaveAttribute("role", "alert");
    expect(message).toHaveClass("border", "border-loss");
    expect(message.previousElementSibling).toBe(await title());
    expect(screen.queryByTestId("pool-panel")).not.toBeInTheDocument();
  });

  it.each([["en"], ["es"]] as const)("draws the no-exchange message in ink-3 when there are no pools, in %s", async (language) => {
    await act(() => i18n.changeLanguage(language));
    stubApi(HEALTH, [], { kind: "ok", body: [] });
    renderAt(<AppRoutes />, "/");

    const message = await (await inPage()).findByText(MESSAGES[language].none);
    expect(message).toHaveClass("text-ink-3");
    expect(message).not.toHaveAttribute("role", "alert");
    expect(message.previousElementSibling).toBe(await title());
    expect(screen.queryByTestId("pool-panel")).not.toBeInTheDocument();
  });

  it("draws none of the three messages once the scope is known", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");
    await screen.findAllByTestId("pool-panel");

    for (const text of [MESSAGES.en.loading, MESSAGES.en.error, MESSAGES.en.none]) {
      expect(screen.queryByText(text)).not.toBeInTheDocument();
    }
  });

  it("keeps the page title in every state", async () => {
    stubApi(HEALTH, [], { kind: "network-error" });
    renderAt(<AppRoutes />, "/");

    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
  });

  it("has the messages under overview.scope in both locales", () => {
    for (const locale of [en, es]) {
      expect(locale.overview.scope.loading).toBeTruthy();
      expect(locale.overview.scope.error).toBeTruthy();
      expect(locale.overview.scope.noExchanges).toBeTruthy();
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
    expect(within(usdt).getByTestId("pool-eyebrow")).toHaveTextContent("Bybit, linear pool in USDT");
    expect(within(btc).getByTestId("pool-eyebrow")).toHaveTextContent("Bybit, inverse pool in BTC");

    await waitFor(() => expect(within(usdt).getByTestId("ledger-lead")).toHaveTextContent("1,284.52"));
    await waitFor(() => expect(within(btc).getByTestId("ledger-lead")).toHaveTextContent("0.12500000"));
    expect(within(usdt).getByTestId("ledger-lead")).toHaveTextContent("USDT");
    expect(within(btc).getByTestId("ledger-lead")).toHaveTextContent("BTC");
    expect(screen.getAllByTestId("ledger-line")).toHaveLength(2);
    expect(screen.queryByText(/777/)).not.toBeInTheDocument();

    expect(performanceCalls(fetchMock).sort()).toEqual([
      expect.stringMatching(/\/performance\/pools\/bybit\/inverse\/BTC$/),
      expect.stringMatching(/\/performance\/pools\/bybit\/linear\/USDT$/),
    ]);
  });

  it("orders the panels: enabled first, then USDT by available balance, then the rest by currency", async () => {
    const at = (available: string) => ({ ...BALANCE, available });
    stubApi(HEALTH, [], {
      kind: "ok",
      body: [
        { ...pool("bybit", "coin-m", "ETH", at("2.00000000")), enabled: false },
        pool("bybit", "coin-m", "ETH2", at("9.00000000")),
        pool("bybit", "coin-m", "BTC", at("0.50000000")),
        pool("bybit", "spot", "USDT", at("100.00")),
        pool("bybit", "usdt-m", "USDT", at("900.00")),
      ],
    });
    renderAt(<AppRoutes />, "/");

    await waitFor(() => expect(screen.getAllByTestId("pool-panel")).toHaveLength(5));
    expect(screen.getAllByTestId("pool-eyebrow").map((node) => node.textContent)).toEqual([
      "Bybit, usdt-m pool in USDT",
      "Bybit, spot pool in USDT",
      "Bybit, coin-m pool in BTC",
      "Bybit, coin-m pool in ETH2",
      "Bybit, coin-m pool in ETH",
    ]);
    // Ranking is not summing: no figure on the page is a total across pools.
    expect(document.body).not.toHaveTextContent("1,000.00");
  });

  it("shows the other exchange's pool, and only its pool, after a tab switch", async () => {
    stubApi(HEALTH, [], POOLS);
    renderAt(<AppRoutes />, "/");
    await screen.findAllByTestId("pool-panel");

    fireEvent.click(screen.getAllByRole("button", { name: "Binance" })[0] as HTMLElement);

    await waitFor(() => expect(screen.getAllByTestId("pool-panel")).toHaveLength(1));
    // The exchange's only pool: the card says it is single.
    expect(screen.getByTestId("pool-eyebrow")).toHaveTextContent("Binance, single USDT pool");
    await waitFor(() => expect(screen.getByTestId("ledger-lead")).toHaveTextContent("777.00"));
  });

  it("requests no report and shows no panel until the exchange is known", async () => {
    const fetchMock = stubApi(HEALTH, [], { kind: "pending" });
    renderAt(<AppRoutes />, "/");
    await (await inPage()).findByText(en.overview.scope.loading);

    expect(screen.queryByTestId("pool-panel")).not.toBeInTheDocument();
    expect(performanceCalls(fetchMock)).toEqual([]);
  });

  it("requests no report and shows no panel when the pools failed", async () => {
    const fetchMock = stubApi(HEALTH, [], { kind: "status", status: 500, body: { detail: "boom" } });
    renderAt(<AppRoutes />, "/");
    await (await inPage()).findByText(en.overview.scope.error);

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
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
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

    // Behind an (i) after the balance's title, closed until asked (L.10), not on the pool's eyebrow.
    const group = await screen.findByTestId("ledger-group-available");
    expect(screen.queryByTestId("balance-stale")).not.toBeInTheDocument();
    fireEvent.click(within(group).getByRole("button", { name: "Balance out of date" }));
    const note = screen.getByTestId("balance-stale");
    expect(note).toHaveTextContent("Balance is out of date: last synced");
    expect(note).toHaveTextContent("2026");
    expect(note.className).not.toContain("text-decision");
    await waitFor(() => expect(screen.getByTestId("ledger-lead")).toHaveTextContent("1,284.52"));
  });

  it("carries no stale flag for a fresh snapshot", async () => {
    stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit", "linear", "USDT", BALANCE)] });
    renderAt(<AppRoutes />, "/");

    const lead = await screen.findByTestId("ledger-lead");
    expect(screen.queryByTestId("balance-stale")).not.toBeInTheDocument();
    expect(within(lead).queryByRole("button")).toBeNull();
  });
});

describe("the range selector", () => {
  const TWO = {
    kind: "ok",
    body: [pool("bybit", "linear", "USDT", BALANCE), pool("bybit", "inverse", "BTC", BALANCE)],
  } as const;

  // RD.3 (S8): the card's figures are all time, so the range drives only the chart. This replaces the old test, in
  // which the ledger line's PnL and return followed the range.
  it("only moves the chart's window: no second report request, and the card's figures stay all time", async () => {
    const fetchMock = stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit", "linear", "USDT", BALANCE)] }, {
      "bybit/linear/USDT": { kind: "ok", body: activeReport("bybit", "linear", "USDT") },
    });
    renderAt(<AppRoutes />, "/");
    await waitFor(() => expect(screen.getByTestId("ledger-pnl")).toHaveTextContent("+99.00"));
    expect(screen.getByTestId("ledger-return")).toHaveTextContent("+7.0%");

    fireEvent.click(screen.getByRole("radio", { name: "7D" }));

    await waitFor(() => expect(screen.getByRole("radio", { name: "7D" })).toBeChecked());
    expect(screen.getByTestId("ledger-pnl")).toHaveTextContent("+99.00");
    expect(screen.getByTestId("ledger-return")).toHaveTextContent("+7.0%");
    expect(performanceCalls(fetchMock)).toHaveLength(1);
  });

  it("is shared by every panel (owner decision 68 Q2): pressing 7D on one moves the other too, each keeping its own figures", async () => {
    stubApi(HEALTH, [], TWO, {
      "bybit/linear/USDT": { kind: "ok", body: activeReport("bybit", "linear", "USDT") },
      "bybit/inverse/BTC": { kind: "ok", body: activeReport("bybit", "inverse", "BTC", "0.41200000") },
    });
    renderAt(<AppRoutes />, "/");
    const [first, second] = (await screen.findAllByTestId("pool-panel")) as [HTMLElement, HTMLElement];
    await waitFor(() => expect(within(second).getByTestId("ledger-pnl")).toBeInTheDocument());
    await waitFor(() => expect(within(first).getByTestId("ledger-pnl")).toBeInTheDocument());

    fireEvent.click(within(first).getByRole("radio", { name: "7D" }));

    await waitFor(() => expect(within(first).getByRole("radio", { name: "7D" })).toBeChecked());
    expect(within(second).getByRole("radio", { name: "7D" })).toBeChecked();
    expect(within(second).getByRole("radio", { name: "30D" })).not.toBeChecked();
    // Each pool keeps its own all-time figures, whatever the range.
    expect(within(first).getByTestId("ledger-pnl")).toHaveTextContent("+99.00USDT");
    expect(within(second).getByTestId("ledger-pnl")).toHaveTextContent("+99.00000000BTC");
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
  return curve === null ? 0 : ((curve.getAttribute("d") ?? "").match(/[MLC]/g) ?? []).length;
}

function finalReturn(scope: HTMLElement): number {
  return Number(within(scope).getByTestId("return-curve").getAttribute("data-final-return"));
}

/**
 * jsdom has no layout, so the sizing of decisions 35 and 36 is pinned as a class and
 * structure contract. The pixel budget it is designed for (1920x915, 1440x900) is in
 * tasks.md, 8o review fixes; it is an estimate, not a measurement.
 */
describe("the overview sizing (decisions 35 and 36)", () => {
  async function renderOne(stale = false) {
    stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit", "linear", "USDT", { ...BALANCE, stale })] }, {
      "bybit/linear/USDT": { kind: "ok", body: activeReport("bybit", "linear", "USDT") },
    });
    renderAt(<AppRoutes />, "/");
    const panel = await screen.findByTestId("pool-panel");
    await within(panel).findByTestId("ledger-line");
    return panel;
  }

  it("fills the available width: neither the panel nor its column has a maximum width", async () => {
    const panel = await renderOne();
    expect(panel.className).not.toMatch(/max-w-/);
    const column = screen.getByTestId("overview-layout");
    expect(column.className).not.toMatch(/max-w-/);
    expect(column).toHaveClass("flex-col", "min-w-0");
    expect(panel).toHaveClass("w-full", "min-w-0");
  });

  it("is one column on every width: the panels stack and nothing sits beside them", async () => {
    await renderOne();
    const layout = screen.getByTestId("overview-layout");
    expect(layout.className).not.toMatch(/grid-cols|22.5rem|flex-row|xl:items-start/);
    expect(layout.parentElement?.querySelectorAll("aside, [data-testid='rail-slot']")).toHaveLength(0);
  });

  it("asks for no side rail: the 1280 px query of the rail is gone", async () => {
    const queries: string[] = [];
    vi.stubGlobal("matchMedia", (query: string) => {
      queries.push(query);
      return { matches: true, media: query, addEventListener: () => undefined, removeEventListener: () => undefined };
    });
    await renderOne();
    expect(queries).not.toContain("(min-width: 1280px)");
  });

  it("draws the chart at a fixed height that does not depend on the panel's width", async () => {
    const panel = await renderOne();
    const svg = within(panel).getByRole("img", { name: CHART_NAME });
    expect(svg).toHaveAttribute("height", "280");
    expect(svg.getAttribute("viewBox")).toMatch(/^0 0 \d+ 280$/);
    expect(svg.getAttribute("class") ?? "").not.toMatch(/h-auto|aspect-/);
  });

  // RD.3 replaces the three tests that pinned the selector in the chart's own header, wrapping with 44 px buttons, and
  // driving the ledger line: the selector is the card header's segmented control and drives only the chart.
  it("puts the range selector in the chart card's header, beside its title", async () => {
    const panel = await renderOne();
    const group = within(panel).getByRole("radiogroup", { name: "Range" });
    const card = within(panel).getByRole("heading", { name: "Compounded return" }).closest("section") as HTMLElement;
    expect(card).toContainElement(group);
    expect(group.parentElement).toBe(within(panel).getByRole("heading", { name: "Compounded return" }).parentElement);
    expect(card).toContainElement(within(panel).getByRole("img", { name: CHART_NAME }));
    expect(within(group).getAllByRole("radio")).toHaveLength(5);
    expect(within(panel).queryByTestId("chart-header")).toBeNull();
  });

  it("drives the chart from the card's selector and leaves the card's figures alone", async () => {
    const panel = await renderOne();
    fireEvent.click(within(panel).getByRole("radio", { name: "7D" }));
    await waitFor(() => expect(within(panel).getByRole("radio", { name: "7D" })).toBeChecked());
    expect(within(panel).getByTestId("ledger-pnl")).toHaveTextContent("+99.00");
  });

  it("keeps the stale note behind the balance's (i), under the balance (L.10)", async () => {
    const panel = await renderOne(true);
    expect(within(panel).queryByTestId("balance-stale")).toBeNull();
    fireEvent.click(within(within(panel).getByTestId("ledger-group-available")).getByRole("button", { name: "Balance out of date" }));
    const note = within(panel).getByTestId("balance-stale");
    expect(note.className).not.toContain("text-decision");
    expect(note).toHaveTextContent("Balance is out of date: last synced");
    expect(within(panel).getByTestId("header-card")).toContainElement(note);
  });

  // RD.3 replaces "keeps the ledger line to its own row: three groups": the row has four figures now.
  it("keeps the figures to their own row: four, with the currency joined to its figure and the balance's unit beside it", async () => {
    const panel = await renderOne();
    expect(within(panel).getByTestId("ledger-line").querySelectorAll("dd")).toHaveLength(4);
    expect(within(panel).getByTestId("ledger-pnl")).toHaveTextContent(/^\+99\.00USDT$/);
    // No space between a figure and its unit, so the two never part at a line break.
    expect(within(panel).getByTestId("ledger-lead")).toHaveTextContent(/^1,284\.52USDT$/);
  });

  it("scrolls only inside main: the page itself grows no scrollbar of its own", async () => {
    await renderOne();
    expect(screen.getByRole("main")).toHaveClass("overflow-auto");
  });
});

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

  it("starts on the 30D window", async () => {
    stubApi(HEALTH, [], ONE, { "bybit/linear/USDT": { kind: "ok", body: consistentReport("bybit", "linear", "USDT") } });
    renderAt(<AppRoutes />, "/");
    const panel = await screen.findByTestId("pool-panel");
    await within(panel).findByTestId("return-curve");

    expect(within(panel).getByRole("radio", { name: "30D" })).toBeChecked();
    expect(chartDays(panel)).toBe(CONSISTENT_DAYS_30D);
  });

  it.each(Object.keys(RANGE_DAYS) as ConsistentRange[])(
    "ends %s on the return the report states for the same range",
    async (range) => {
      const report = consistentReport("bybit", "linear", "USDT");
      stubApi(HEALTH, [], ONE, { "bybit/linear/USDT": { kind: "ok", body: report } });
      renderAt(<AppRoutes />, "/");
      const panel = await screen.findByTestId("pool-panel");
      await within(panel).findByTestId("return-curve");

      fireEvent.click(within(panel).getByRole("radio", { name: range }));

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
      fireEvent.click(within(panel).getByRole("radio", { name: range }));
      await waitFor(() => expect(within(panel).getByRole("radio", { name: range })).toBeChecked());
      counts.push(chartDays(panel));
    }
    expect(counts).toEqual([2, 8, 23, 92, 101]);
  });

  it("is shared by every panel (owner decision 68 Q2): 7D on one redraws both charts, each from its own curve", async () => {
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

    fireEvent.click(within(first).getByRole("radio", { name: "7D" }));

    await waitFor(() => expect(chartDays(first)).toBe(2));
    expect(chartDays(second)).toBe(2);
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
    fireEvent.click(within(panel).getByRole("radio", { name: "All" }));
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
