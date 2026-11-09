import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import {
  emptyPerformance,
  jsonResponse,
  lock,
  openOrder,
  openPosition,
  openState,
  pool,
  renderAt,
  resetExchangeScope,
  stubApi,
  subscriptionOf,
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
    subscription: null,
    enabled: true,
    archived_at: null,
    allowed_pairs: ["SOLUSDT"],
    uptime: { seconds: 12 * DAY_S + 3600, first_enabled_at: "2026-09-18T10:00:00Z", baseline: false },
    visibility: "PRIVATE",
    share_token: null,
    secret_last4: "x4F2",
    description: null,
    subscribers: 1,
    live_subscribers: 0,
    created_at: "2026-09-01T10:00:00Z",
    capital: null,
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
  it.each([
    [3, 2, "3 subscribers, 2 live", "3 · 2 live"],
    [1, 0, "1 subscriber, 0 live", "1 · 0 live"],
  ])("tells its author who holds it: %i and %i live read as %s", async (subscribers, live, text, visible) => {
    const api = strategiesApi([strategy({ subscribers, live_subscribers: live })]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const row = await screen.findByTestId("strategy-row");
    const held = within(row).getByTestId("strategy-subscribers");
    expect(within(held.previousElementSibling as HTMLElement).getByRole("img", { name: text })).toBeInTheDocument();
    // The live count is a figure, not a label: it stays in sight beside the icon.
    expect(held.textContent).toBe(visible);
  });

  it("tells its author the capital in the strategy's own currency", async () => {
    const api = strategiesApi([strategy({ capital: "300" })]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const row = await screen.findByTestId("strategy-row");
    expect(within(row).getByTestId("strategy-capital")).toHaveTextContent("300.00 USDT");
  });

  it("claims no capital under the server's brake", async () => {
    const api = strategiesApi([strategy({ capital: null })]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const row = await screen.findByTestId("strategy-row");
    // The card keeps the figure's place and shows the dash the other cards show (owner, 2026-11-08).
    expect(within(row).getByTestId("strategy-capital").textContent).toBe("—");
  });

  it("draws an aria-hidden Plus left of New strategy and leaves its name as it was", async () => {
    const api = strategiesApi([strategy()]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");
    await screen.findByText("Alpha");

    const button = screen.getByRole("button", { name: en.strategies.new.open });
    const svg = button.querySelector("svg");
    expect(svg).toHaveClass("lucide-plus", "size-4", "shrink-0");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(button.firstElementChild).toBe(svg);
    expect(button).toHaveClass("inline-flex", "items-center", "gap-1.5");
    expect(button).toHaveAccessibleName("New strategy");
  });

  it("test_archived_excluded_by_default_toggle_shows_them", async () => {
    const api = strategiesApi([strategy(), ARCHIVED]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");

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
    renderAt(<AppRoutes />, "/strategies/authored");

    const row = await screen.findByTestId("strategy-row");
    expect(within(row).getByRole("link", { name: "Alpha" })).toHaveAttribute(
      "href",
      "/strategies/11111111-1111-4111-8111-111111111111",
    );
    // Decision 39: the venue and the allowed pairs, in the API's order. The exchange
    // (the operator is on its tab) and the settlement currency (shown by the PnL) are not repeated.
    const subLine = within(row).getByTestId("strategy-market");
    expect(subLine.textContent).toBe("usdt-m · ETHUSDT, BTCUSDT");
    expect(subLine).not.toHaveTextContent("bybit");
    expect(subLine.textContent).not.toMatch(/\bUSDT\b/);
    expect(within(row).getByRole("switch", { name: "Enable Alpha" })).toHaveAttribute("aria-checked", "true");
    const uptime = within(row).getByTestId("strategy-uptime");
    expect(
      within(uptime.previousElementSibling as HTMLElement).getByRole("img", { name: "active 12 days" }),
    ).toBeInTheDocument();
    expect(uptime.textContent).toBe("12");
    await waitFor(() => expect(within(row).getByTestId("strategy-trades")).toHaveTextContent("7"));
    // Each icon is centred over the figure it heads; the PnL and the return are icons too (owner, 2026-11-06),
    // so the figures share one height and line up.
    for (const [testId, name] of [
      ["strategy-trades", en.strategies.card.trades],
      ["strategy-pnl", en.strategies.card.pnl],
      ["strategy-return", en.strategies.card.return],
    ] as const) {
      const term = within(row).getByTestId(testId).previousElementSibling as HTMLElement;
      expect(within(term).getByRole("img", { name })).toBeInTheDocument();
      expect(term.textContent).toBe("");
      expect(term.parentElement).toHaveClass("flex", "w-fit", "flex-col", "items-center");
    }
    expect(within(row).getByTestId("strategy-pnl")).toHaveTextContent("+41.20 USDT");
    expect(within(row).getByTestId("strategy-return")).toHaveTextContent("+3.4%");
  });

  it("test_the_strategies_list_shows_no_rows_share", async () => {
    const api = strategiesApi([strategy({ subscription: subscriptionOf("11111111-1111-4111-8111-111111111111", "37.5") })]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");

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
    renderAt(<AppRoutes />, "/strategies/authored");

    const row = await screen.findByTestId("strategy-row");
    expect(within(row).getByTestId("strategy-market").textContent).toBe("usdt-m");
  });

  it("shows a never-enabled strategy as off, with no activation claim", async () => {
    const never = strategy({
      enabled: false,
      uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    });
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([never]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const row = await screen.findByTestId("strategy-row");
    expect(within(row).getByRole("switch")).toHaveAttribute("aria-checked", "false");
    const uptime = within(row).getByTestId("strategy-uptime");
    expect(within(uptime.previousElementSibling as HTMLElement).getByRole("img", { name: en.strategies.row.neverEnabled })).toBeInTheDocument();
    expect(uptime.textContent).toBe("—");
  });

  it("says 'at least' when the first activation is only a baseline", async () => {
    const baseline = strategy({ uptime: { seconds: 3 * DAY_S, first_enabled_at: "2026-09-29T00:00:00Z", baseline: true } });
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([baseline]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const uptime = await screen.findByTestId("strategy-uptime");
    expect(
      within(uptime.previousElementSibling as HTMLElement).getByRole("img", { name: "active at least 3 days" }),
    ).toBeInTheDocument();
    // A lower bound must not read as an exact count.
    expect(uptime.textContent).toBe("≥3");
  });

  it("lists only the selected exchange's strategies, and follows a tab switch", async () => {
    const other = strategy({ id: "33333333-3333-4333-8333-333333333333", name: "Gamma", exchange: "binance", venue: "usdt-m" });
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy(), other]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    expect(await screen.findByText("Alpha")).toBeInTheDocument();
    expect(screen.queryByText("Gamma")).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Binance" })[0] as HTMLElement);

    expect(await screen.findByText("Gamma")).toBeInTheDocument();
    expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
  });

  it("says so when the exchange has no strategies", async () => {
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    expect(await screen.findByText(en.strategies.empty)).toBeInTheDocument();
  });

  it("shows a failed list as an error, never as an empty list", async () => {
    stubApi(HEALTH, [], POOLS, {}, (url) =>
      /\/strategies(\?|$)/.test(url) ? Promise.resolve(jsonResponse({ detail: "boom" }, 500)) : undefined,
    );
    renderAt(<AppRoutes />, "/strategies/authored");

    expect(await screen.findByRole("alert")).toHaveTextContent(en.strategies.error);
    expect(screen.queryByText(en.strategies.empty)).not.toBeInTheDocument();
  });

  it("shows a malformed list body as an error", async () => {
    stubApi(HEALTH, [], POOLS, {}, (url) =>
      /\/strategies(\?|$)/.test(url) ? Promise.resolve(jsonResponse({ items: [] })) : undefined,
    );
    renderAt(<AppRoutes />, "/strategies/authored");

    expect(await screen.findByRole("alert")).toHaveTextContent(en.strategies.error);
  });

  it("shows no strategy until the exchange scope is known", async () => {
    const api = strategiesApi([strategy()]);
    stubApi(HEALTH, [], { kind: "pending" }, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");

    expect(await screen.findByText(en.strategies.scopeLoading)).toBeInTheDocument();
    expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
  });

  it("blanks only a row's figures when its report fails, and says so", async () => {
    const api = strategiesApi([strategy()], () => Promise.resolve(jsonResponse({ detail: "boom" }, 500)));
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");

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
    renderAt(<AppRoutes />, "/strategies/authored");

    const row = await screen.findByTestId("strategy-row");
    expect(await within(row).findByText(en.strategies.row.performanceError)).toBeInTheDocument();
    expect(within(row).queryByTestId("strategy-pnl")).not.toBeInTheDocument();
  });
});

describe("the enable switch asks first (owner, 2026-11-06)", () => {
  const patches = (api: ReturnType<typeof strategiesApi>) => api.calls.filter((call) => call.method === "PATCH");

  it("pressed on an enabled strategy, asks to disable it, says what that does, and sends nothing yet", async () => {
    const api = strategiesApi([strategy()]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");
    const row = await screen.findByTestId("strategy-row");

    fireEvent.click(within(row).getByRole("switch"));

    const dialog = await screen.findByRole("dialog", { name: "Disable Alpha?" });
    expect(dialog).toHaveTextContent(en.strategies.enableDialog.disableBody.replace("{{name}}", "Alpha"));
    expect(within(row).getByRole("switch")).toHaveAttribute("aria-checked", "true");
    expect(patches(api)).toHaveLength(0);
  });

  it("pressed on a disabled strategy, asks to enable it", async () => {
    const api = strategiesApi([strategy({ enabled: false })]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");
    const row = await screen.findByTestId("strategy-row");

    fireEvent.click(within(row).getByRole("switch"));

    const dialog = await screen.findByRole("dialog", { name: "Enable Alpha?" });
    expect(dialog).toHaveTextContent(en.strategies.enableDialog.enableBody.replace("{{name}}", "Alpha"));
    expect(patches(api)).toHaveLength(0);
  });

  it.each([
    ["Cancel", () => fireEvent.click(screen.getByRole("button", { name: en.strategies.enableDialog.cancel }))],
    ["Escape", () => fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" })],
    ["the browser's cancel", () => fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }))],
  ])("%s closes the question and leaves the strategy as it was", async (_name, dismiss) => {
    const api = strategiesApi([strategy()]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");
    const row = await screen.findByTestId("strategy-row");

    fireEvent.click(within(row).getByRole("switch"));
    await screen.findByRole("dialog");
    dismiss();

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(within(row).getByRole("switch")).toHaveAttribute("aria-checked", "true");
    expect(patches(api)).toHaveLength(0);
  });

  it("confirmed, sends the opposite value for that strategy and closes the question", async () => {
    const api = strategiesApi([strategy()]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");
    const row = await screen.findByTestId("strategy-row");

    fireEvent.click(within(row).getByRole("switch"));
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: en.strategies.enableDialog.disable }),
    );

    await waitFor(() => expect(patches(api)).toHaveLength(1));
    expect(patches(api)[0]).toMatchObject({ body: { enabled: false } });
    expect(patches(api)[0]?.url).toMatch(/\/strategies\/11111111-/);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("shows a refused change inside the question instead of swallowing it", async () => {
    const api = strategiesApi([strategy()]);
    stubApi(HEALTH, [], POOLS, {}, (url, init) =>
      init?.method === "PATCH" ? Promise.resolve(jsonResponse({ detail: "no" }, 409)) : api.route(url, init),
    );
    renderAt(<AppRoutes />, "/strategies/authored");
    const row = await screen.findByTestId("strategy-row");

    fireEvent.click(within(row).getByRole("switch"));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: en.strategies.enableDialog.disable }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(en.strategies.row.toggleError);
  });
});

/** The class tokens of an element, so a test names a class and not a substring of the whole attribute. */
const classesOf = (element: Element) => element.className.split(/\s+/);

describe("the author's card", () => {
  const ID = "11111111-1111-4111-8111-111111111111";

  /** A report with a deepest fall and a win count, so the card's four reported figures all have a value. */
  function reportWithPairs(id: string) {
    return {
      ...strategyReport(id),
      max_drawdown: "-0.0820000000",
      by_pair: [
        { pair: "SOLUSDT", trades: 4, wins: 3, win_rate: "0.75", pnl: "30.00", return: "0.02" },
        { pair: "ETHUSDT", trades: 3, wins: 1, win_rate: "0.3333", pnl: "11.20", return: "0.01" },
      ],
    };
  }

  async function oneCard(overrides: Record<string, unknown> = {}, perf?: ExtraRoute) {
    const api = strategiesApi(
      [strategy(overrides)],
      perf ?? ((url) => Promise.resolve(jsonResponse(reportWithPairs(/([^/]+)$/.exec(url)?.[1] ?? "")))),
    );
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");
    return await screen.findByTestId("strategy-row");
  }

  it("draws the same figures as Explore, from the author's own report", async () => {
    const row = await oneCard({ subscribers: 3, live_subscribers: 2, capital: "300" });
    await waitFor(() => expect(within(row).getByTestId("strategy-trades")).toHaveTextContent("7"));

    expect(within(row).getByTestId("strategy-age")).not.toBeEmptyDOMElement();
    expect(within(row).getByTestId("strategy-uptime").textContent).toBe("12");
    expect(within(row).getByTestId("strategy-return")).toHaveTextContent("+3.4%");
    expect(within(row).getByTestId("strategy-deepest")).toHaveTextContent("-8.2%");
    // Wins over closed trades across the pairs: 4 of 7.
    expect(within(row).getByTestId("strategy-winrate")).toHaveTextContent("57.1%");
    expect(within(row).getByTestId("strategy-subscribers").textContent).toBe("3 · 2 live");
    expect(within(row).getByTestId("strategy-capital")).toHaveTextContent("300.00 USDT");
    expect(within(row).getByTestId("strategy-pnl")).toHaveTextContent("+41.20 USDT");
  });

  it("names every figure by a tooltip on its icon", async () => {
    const row = await oneCard({ capital: "300" });
    await waitFor(() => expect(within(row).getByTestId("strategy-trades")).toHaveTextContent("7"));
    for (const [testId, name] of [
      ["strategy-age", en.strategies.card.age],
      ["strategy-trades", en.strategies.card.trades],
      ["strategy-return", en.strategies.card.return],
      ["strategy-deepest", en.strategies.card.deepest],
      ["strategy-winrate", en.strategies.card.winRate],
      ["strategy-capital", en.strategies.card.capital],
      ["strategy-pnl", en.strategies.card.pnl],
    ] as const) {
      const term = within(row).getByTestId(testId).previousElementSibling as HTMLElement;
      expect(within(term).getByRole("img", { name })).toBeInTheDocument();
    }
  });

  it("shows a dash where there is no figure yet", async () => {
    const row = await oneCard({ capital: null }, () => Promise.resolve(jsonResponse(null, 404)));
    await waitFor(() => expect(within(row).getByTestId("strategy-trades")).toHaveTextContent("—"));
    for (const id of ["strategy-return", "strategy-deepest", "strategy-winrate", "strategy-capital", "strategy-pnl"]) {
      expect(within(row).getByTestId(id).textContent).toBe("—");
    }
  });

  it("keeps the venue and the pairs on the market line", async () => {
    const row = await oneCard({ allowed_pairs: ["ETHUSDT", "BTCUSDT"] });
    expect(within(row).getByTestId("strategy-market").textContent).toBe("usdt-m · ETHUSDT, BTCUSDT");
  });

  it("carries a switch instead of an enabled word", async () => {
    const row = await oneCard();
    expect(within(row).queryByTestId("strategy-enabled")).toBeNull();
    expect(within(row).getByRole("switch", { name: "Enable Alpha" })).toBeInTheDocument();
  });

  it("opens the strategy from the whole card, the title being its one link", async () => {
    const row = await oneCard();
    const links = within(row).getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", `/strategies/${ID}`);
    expect(classesOf(row)).toContain("relative");
    expect(classesOf(links[0] as HTMLElement)).toEqual(expect.arrayContaining(["after:absolute", "after:inset-0"]));
    // The switch stays above the stretched link, so pressing it does not open the strategy.
    expect(within(row).getByRole("switch").closest(".z-10")).not.toBeNull();
  });

  it("draws its figures in the grid every card shares: four a row on a phone, centred", async () => {
    const row = await oneCard();
    const grid = within(row).getByTestId("strategy-return").closest("dl") as HTMLElement;
    expect(classesOf(grid)).toEqual(expect.arrayContaining(["grid", "grid-cols-4", "place-items-center", "lg:grid-cols-8"]));
  });

  it("says once that its figures could not be read, and draws no PnL", async () => {
    const row = await oneCard({}, () => Promise.resolve(jsonResponse({ detail: "boom" }, 500)));
    expect(await within(row).findByText(en.strategies.row.performanceError)).toBeInTheDocument();
    expect(within(row).queryByTestId("strategy-pnl")).toBeNull();
  });

  it("no longer shows the open-state line above the list", async () => {
    const row = await oneCard();
    expect(row).toBeInTheDocument();
    // Let the positions read finish: the line drew its figures only once it had an answer.
    await waitFor(() => expect(screen.queryByText(en.positions.state.loading)).not.toBeInTheDocument());
    // The line read "Open: … Orders in flight: … Last read: … Read again".
    expect(screen.queryByText("Open:")).not.toBeInTheDocument();
    expect(screen.queryByText("Orders in flight:")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Read again" })).not.toBeInTheDocument();
  });
});

describe("the author's list is sorted by the figure the cards show", () => {
  const A = "a1a1a1a1-a1a1-41a1-81a1-a1a1a1a1a1a1";
  const B = "b1b1b1b1-b1b1-41b1-81b1-b1b1b1b1b1b1";
  const C = "c1c1c1c1-c1c1-41c1-81c1-c1c1c1c1c1c1";
  const rows = [
    strategy({ id: A, name: "Aaa", created_at: "2026-09-10T00:00:00Z", subscribers: 1, capital: "100" }),
    strategy({ id: B, name: "Bbb", created_at: "2026-08-10T00:00:00Z", subscribers: 5, capital: "50" }),
    strategy({ id: C, name: "Ccc", created_at: "2026-09-20T00:00:00Z", subscribers: 3, capital: "900" }),
  ];
  const figures: Record<string, { ret: string; trades: number }> = {
    [A]: { ret: "0.10", trades: 2 },
    [B]: { ret: "0.30", trades: 9 },
    [C]: { ret: "0.20", trades: 5 },
  };
  const failing = { c: false };

  function perf(url: string) {
    const id = /([^/]+)$/.exec(url)?.[1] ?? "";
    if (id === C && failing.c) return Promise.resolve(jsonResponse({ detail: "boom" }, 500));
    const report = strategyReport(id);
    const entry = figures[id] ?? { ret: "0", trades: 0 };
    const all = { range: "All", pnl: "1.00", return: entry.ret, trade_count: entry.trades };
    return Promise.resolve(
      jsonResponse({
        ...report,
        trade_count: entry.trades,
        ranges: [...report.ranges.filter((range) => range.range !== "All"), all],
      }),
    );
  }

  beforeEach(() => {
    failing.c = false;
  });

  const names = () =>
    screen.getAllByTestId("strategy-row").map((row) => within(row).getAllByRole("link")[0]?.textContent);

  async function mount() {
    stubApi(HEALTH, [], POOLS, {}, strategiesApi(rows, perf).route);
    renderAt(<AppRoutes />, "/strategies/authored");
    await screen.findAllByTestId("strategy-row");
    await waitFor(() => expect(screen.getAllByTestId("strategy-trades").map((node) => node.textContent)).not.toContain("…"));
  }
  const press = (name: string) => fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${name}`) }));

  it("starts on return, largest first, the contribution to the pool", async () => {
    await mount();
    expect(names()).toEqual(["Bbb", "Ccc", "Aaa"]);
    expect(screen.getByRole("button", { name: /^Return/ })).toHaveAttribute("aria-pressed", "true");
  });

  it.each([
    ["Closed trades", ["Bbb", "Ccc", "Aaa"]],
    ["Subscribers", ["Bbb", "Ccc", "Aaa"]],
    ["Capital", ["Ccc", "Aaa", "Bbb"]],
    ["Age", ["Bbb", "Aaa", "Ccc"]],
  ])("%s sorts descending first, then ascending on a second press", async (key, descending) => {
    await mount();
    press(key);
    expect(names()).toEqual(descending);
    press(key);
    expect(names()).toEqual([...descending].reverse());
    press(key);
    expect(names()).toEqual(descending);
  });

  it("a card whose figures failed sorts last both ways", async () => {
    failing.c = true;
    await mount();
    expect(names()).toEqual(["Bbb", "Aaa", "Ccc"]);
    press("Return");
    expect(names()).toEqual(["Aaa", "Bbb", "Ccc"]);
  });
});

/** T15 (spec "The Strategies Page Shows Nothing Of Another Exchange"): what the page selects, per exchange. */
describe("the Strategies page shows nothing of another exchange", () => {
  const BINANCE_ID = "b1b1b1b1-b1b1-41b1-81b1-b1b1b1b1b1b1";
  const BYBIT_ID = "b2b2b2b2-b2b2-42b2-82b2-b2b2b2b2b2b2";
  const HIDDEN_ID = "a1a1a1a1-a1a1-41a1-81a1-a1a1a1a1a1a1";
  const BINANCE_POOL = { exchange: "binance", venue: "usdt-m", settlement_currency: "USDT" };
  const BYBIT_POOL = { exchange: "bybit", venue: "usdt-m", settlement_currency: "USDT" };

  const binanceStrategy = strategy({ id: BINANCE_ID, name: "Binance Strat", exchange: "binance", allowed_pairs: ["ONEUSDT"] });
  const bybitStrategy = strategy({ id: BYBIT_ID, name: "Bybit Strat", exchange: "bybit", allowed_pairs: ["TWOUSDT"] });

  /** One answer: one position on binance, four on bybit (one the stored fault) and one order in flight on bybit. */
  const ANSWER = openState(
    [
      openPosition({ strategy_id: BINANCE_ID, strategy_name: "Binance Strat", pool: BINANCE_POOL, markets: ["ONEUSDT"] }),
      openPosition({ strategy_id: BYBIT_ID, strategy_name: "Bybit Strat", pool: BYBIT_POOL, markets: ["TWOUSDT"] }),
      openPosition({
        strategy_id: HIDDEN_ID,
        strategy_name: "Hidden Archived",
        strategy_archived: true,
        pool: BYBIT_POOL,
        markets: ["THREEUSDT"],
        origin: "rehearsal",
      }),
      openPosition({
        strategy_id: null,
        strategy_archived: null,
        strategy_name: "Unmatched Name",
        pool: BYBIT_POOL,
        markets: ["FOURUSDT"],
        figures_missing: "NO_FACTS",
      }),
      // The stored fault: the visible binance strategy's position, in a bybit pool.
      openPosition({ strategy_id: BINANCE_ID, strategy_name: "Binance Strat", pool: BYBIT_POOL, markets: ["SIXUSDT"] }),
    ],
    [
      openOrder({
        strategy_id: HIDDEN_ID,
        strategy_name: "Order Strat",
        strategy_archived: true,
        pool: BYBIT_POOL,
        market: "FIVEUSDT",
      }),
    ],
  );

  const BYBIT_ONLY = ["TWOUSDT", "THREEUSDT", "FOURUSDT", "FIVEUSDT", "SIXUSDT", "Hidden Archived", "Unmatched Name", "Order Strat", "Bybit Strat"];

  async function mountPage(body: unknown) {
    const api = strategiesApi([binanceStrategy, bybitStrategy]);
    const fetchMock = stubApi(HEALTH, [], POOLS, {}, api.route, {}, undefined, { kind: "ok", body });
    renderAt(<AppRoutes />, "/strategies/authored");
    // The scope starts on the first exchange (bybit); the owner moves to binance first.
    await screen.findByText("Bybit Strat");
    fireEvent.click(screen.getAllByRole("button", { name: "Binance" })[0] as HTMLElement);
    await screen.findByText("Binance Strat");
    return fetchMock;
  }

  const positionsCalls = (api: ReturnType<typeof stubApi>) =>
    api.mock.calls.filter(([url]) => String(url).endsWith("/positions/open")).length;

  it("counts and draws only binance's elements on the binance tab, then only bybit's with no new request", async () => {
    const fetchMock = await mountPage(ANSWER);

    const row = screen.getByTestId("strategy-row");
    expect(within(row).getByRole("link", { name: "Binance Strat" })).toBeInTheDocument();
    await waitFor(() =>
      expect(within(row).queryAllByRole("listitem").map((item) => item.textContent)).toEqual(["ONEUSDT · LONG · Live"]),
    );
    for (const text of BYBIT_ONLY) expect(document.body.textContent ?? "", text).not.toContain(text);

    const before = positionsCalls(fetchMock);
    fireEvent.click(screen.getAllByRole("button", { name: "Bybit" })[0] as HTMLElement);
    await screen.findByText("Bybit Strat");

    const bybitRow = screen.getByTestId("strategy-row");
    await waitFor(() =>
      expect(within(bybitRow).queryAllByRole("listitem").map((item) => item.textContent)).toEqual(["TWOUSDT · LONG · Live"]),
    );
    // The open-state line is gone (owner, 2026-11-08): nothing on the page lists what the chips do not.
    expect(screen.queryByText(/Not on this list/)).not.toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toContain("ONEUSDT");
    expect(positionsCalls(fetchMock)).toBe(before);
  });

  it("draws an element on no tab nowhere, and no line says that it exists (owner decision Q7, 2026-10-13)", async () => {
    const orphans = openState(
      [
        openPosition({
          strategy_id: null,
          strategy_archived: null,
          strategy_name: "Nowhere Name",
          pool: { exchange: "kraken", venue: "usdt-m", settlement_currency: "USDT" },
          markets: ["NOWHEREUSDT"],
          figures_missing: "NO_FACTS",
        }),
      ],
      [
        openOrder({
          strategy_id: null,
          strategy_name: "Orphan Order",
          pool: { exchange: "kraken", venue: "usdt-m", settlement_currency: "USDT" },
          market: "ORPHANUSDT",
        }),
      ],
    );
    await mountPage(orphans);

    for (const tab of ["Binance", "Bybit"]) {
      fireEvent.click(screen.getAllByRole("button", { name: tab })[0] as HTMLElement);
      await screen.findByText(tab === "Binance" ? "Binance Strat" : "Bybit Strat");
      await waitFor(() => expect(screen.queryByText(en.positions.state.loading)).not.toBeInTheDocument());
      expect(within(screen.getByTestId("strategy-row")).queryAllByRole("listitem")).toHaveLength(0);
      const text = document.body.textContent ?? "";
      for (const hidden of ["Nowhere Name", "NOWHEREUSDT", "Orphan Order", "ORPHANUSDT", "kraken"]) expect(text).not.toContain(hidden);
      expect(screen.queryByText(/Not on this list/)).not.toBeInTheDocument();
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
