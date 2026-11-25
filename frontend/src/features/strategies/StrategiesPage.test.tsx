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
    stop_loss_pct: "10.00",
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
  vi.useRealTimers();
  vi.unstubAllGlobals();
  lock();
});

/** The list's table, named by its card's title. */
const authoredTable = () => screen.findByRole("table", { name: en.strategies.table.title.authored });

describe("the strategies table", () => {
  it("is one table in a card with its title and its count, one row a strategy and no column of open positions (S15)", async () => {
    const api = strategiesApi([strategy(), strategy({ id: "33333333-3333-4333-8333-333333333333", name: "Beta" })]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const table = await authoredTable();
    expect(screen.getByTestId("strategies-count")).toHaveTextContent("2 strategies");
    expect(within(table).getAllByRole("columnheader").map((head) => head.textContent)).toEqual([
      "Strategy",
      "Pairs (USDT-M)",
      "Since",
      "PnL (USDT)",
      "PnL (%)",
      "Max drawdown",
      "Win rate",
      "Subs.",
      "AuM (USDT)",
      "Actions",
    ]);
    expect(screen.getAllByTestId("strategy-row")).toHaveLength(2);
    // The open positions are seen on the strategy's own page: the list draws none of them.
    expect(within(table).queryByRole("list")).toBeNull();
    expect(within(table).queryByText(/open/i)).toBeNull();
  });

  it("starts the four record columns at the start of their cell and ends Subs. and AuM at the end (L23)", async () => {
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy()]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const table = await authoredTable();
    const row = screen.getByTestId("strategy-row");
    const heads = within(table).getAllByRole("columnheader");
    const cells = within(row).getAllByRole("cell");
    for (const index of [3, 4, 5, 6]) {
      expect(heads[index], `head ${index}`).toHaveClass("text-left");
      expect(cells[index], `cell ${index}`).toHaveClass("text-left");
    }
    for (const index of [7, 8]) {
      expect(heads[index], `head ${index}`).toHaveClass("text-right");
      expect(cells[index], `cell ${index}`).toHaveClass("text-right");
    }
  });

  it("names the strategy as the link to its page, and that link is the row's only one", async () => {
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy()]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const row = await screen.findByTestId("strategy-row");
    const links = within(row).getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/strategies/11111111-1111-4111-8111-111111111111");
    expect(links[0]).toHaveAccessibleName("Alpha");
  });

  it("marks a running strategy with a gain dot and a stopped one with a grey dot, the word in a tooltip, and no switch (S15)", async () => {
    const stopped = strategy({ id: "33333333-3333-4333-8333-333333333333", name: "Beta", enabled: false });
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy(), stopped]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const [alpha, beta] = await screen.findAllByTestId("strategy-row");
    const on = within(alpha as HTMLElement).getByTestId("strategy-enabled");
    expect(on).toHaveAccessibleName(en.strategies.detail.enabled);
    expect(on).toHaveClass("bg-gain");
    const off = within(beta as HTMLElement).getByTestId("strategy-enabled");
    expect(off).toHaveAccessibleName(en.strategies.detail.disabled);
    // A stopped strategy is not a fault: grey, never the loss colour.
    expect(off).toHaveClass("bg-ink-3");
    expect(off).not.toHaveClass("bg-loss");
    expect(screen.queryByRole("switch")).toBeNull();

    fireEvent.mouseEnter(on.parentElement as HTMLElement);
    expect(within(alpha as HTMLElement).getByRole("tooltip")).toHaveTextContent(en.strategies.detail.enabled);
  });

  it("writes one pair as its symbol and several as their count, the list in a tooltip (L22)", async () => {
    const two = strategy({ id: "33333333-3333-4333-8333-333333333333", name: "Beta", allowed_pairs: ["ETHUSDT", "BTCUSDT"] });
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy(), two]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const [alpha, beta] = await screen.findAllByTestId("strategy-row");
    const one = within(alpha as HTMLElement).getByTestId("strategy-pairs");
    expect(one).toHaveTextContent(/^SOLUSDT$/);
    const many = within(beta as HTMLElement).getByTestId("strategy-pairs");
    expect(many).toHaveTextContent(/^2 pairs$/);
    expect(many).toHaveClass("underline", "decoration-dotted");
    fireEvent.mouseEnter(many.parentElement as HTMLElement);
    expect(within(beta as HTMLElement).getByRole("tooltip")).toHaveTextContent("ETHUSDT, BTCUSDT");
  });

  it("writes no pair for a strategy with none, a dash", async () => {
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy({ allowed_pairs: [] })]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    expect(await screen.findByTestId("strategy-pairs")).toHaveTextContent(/^—$/);
  });

  it("shows the day it started, the whole period in the tooltip (owner, 2026-11-25)", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-17T12:00:00Z"));
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy()]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const since = await screen.findByTestId("strategy-age");
    expect(since).toHaveTextContent(/^Sep 01, 2026$/);
    fireEvent.mouseEnter(since.parentElement as HTMLElement);
    expect(within(screen.getByTestId("strategy-row")).getByRole("tooltip")).toHaveTextContent("Sep 1, 2026 – Nov 17, 2026");
  });

  it("tells its author how many trade it live and with how much, the capital in the header's currency", async () => {
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy({ subscribers: 3, live_subscribers: 2, capital: "300" })]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const row = await screen.findByTestId("strategy-row");
    expect(within(row).getByTestId("strategy-subscribers").textContent).toBe("2");
    // The header says USDT once; the cell is the number alone.
    expect(within(row).getByTestId("strategy-capital").textContent).toBe("300.00");
  });

  it("claims no capital under the server's brake: a dash", async () => {
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy({ capital: null })]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const row = await screen.findByTestId("strategy-row");
    expect(within(row).getByTestId("strategy-capital").textContent).toBe("—");
  });

  it("keeps each figure in its own pool's currency, so a list that mixes them writes the unit in the cell (rule 7)", async () => {
    const coin = strategy({ id: "33333333-3333-4333-8333-333333333333", name: "Coin", settlement_currency: "BTC", capital: "0.5" });
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy({ capital: "300" }), coin]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const table = await authoredTable();
    const heads = within(table).getAllByRole("columnheader").map((head) => head.textContent);
    expect(heads).toContain("PnL");
    expect(heads).toContain("AuM");
    const [alpha, bitcoin] = screen.getAllByTestId("strategy-row");
    expect(within(alpha as HTMLElement).getByTestId("strategy-capital")).toHaveTextContent("300.00USDT");
    expect(within(bitcoin as HTMLElement).getByTestId("strategy-capital")).toHaveTextContent("0.50000000BTC");
  });

  it("draws an aria-hidden Plus left of New strategy and leaves its name as it was", async () => {
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy()]).route);
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

  it("keeps the search, the sort and New strategy together above the table, in one card (S15)", async () => {
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy()]).route);
    renderAt(<AppRoutes />, "/strategies/authored");
    await authoredTable();

    const toolbar = screen.getByTestId("list-toolbar");
    const card = toolbar.closest("section") as HTMLElement;
    expect(within(card).getByRole("group", { name: en.strategies.sort.label })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: en.strategies.new.open })).toBeInTheDocument();
    expect(within(card).queryByRole("table")).toBeNull();
  });

  it("shows a never-enabled strategy as off, with no activation claim", async () => {
    const never = strategy({
      enabled: false,
      uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    });
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([never]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const row = await screen.findByTestId("strategy-row");
    expect(within(row).getByTestId("strategy-enabled")).toHaveAccessibleName(en.strategies.detail.disabled);
    expect(within(row).getByRole("button", { name: "Enable Alpha" })).toBeInTheDocument();
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
    expect(screen.queryByRole("table")).toBeNull();
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
});

describe("the archived strategies, from the note under the table (L21)", () => {
  it("leaves the search card without a checkbox and says how many archived ones are hidden, with the link that shows them", async () => {
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy(), ARCHIVED]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const table = await authoredTable();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(within(screen.getByTestId("list-toolbar")).queryByText(en.strategies.archivedToggle)).toBeNull();
    const note = screen.getByTestId("archived-note");
    expect(note).toHaveTextContent("1 archived strategy is hidden. Show archived");
    expect(note.closest("section")).toContainElement(table);
    expect(within(note).getByRole("button", { name: en.strategies.archivedToggle })).toBeInTheDocument();
    expect(screen.queryByText("Old Beta")).not.toBeInTheDocument();
  });

  it("shows the archived ones from the link and hides them again from the same place", async () => {
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy(), ARCHIVED]).route);
    renderAt(<AppRoutes />, "/strategies/authored");
    expect(await screen.findByText("Alpha")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: en.strategies.archivedToggle }));

    expect(await screen.findByText("Old Beta")).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByTestId("strategies-count")).toHaveTextContent("2 strategies");
    const archivedRow = screen.getByText("Old Beta").closest("[data-testid='strategy-row']") as HTMLElement;
    expect(within(archivedRow).getByText(en.strategies.row.archived)).toBeInTheDocument();
    // An archived strategy never changes again: its button is unavailable.
    expect(within(archivedRow).getByRole("button", { name: "Enable Old Beta" })).toBeDisabled();
    expect(screen.getByTestId("archived-note")).toHaveTextContent("1 archived strategy is shown. Hide archived");

    fireEvent.click(screen.getByRole("button", { name: en.strategies.table.hideArchived }));
    await waitFor(() => expect(screen.queryByText("Old Beta")).not.toBeInTheDocument());
    expect(screen.getByTestId("archived-note")).toHaveTextContent("1 archived strategy is hidden. Show archived");
  });

  it("draws no note while the exchange has no archived strategy", async () => {
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy()]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    await authoredTable();
    expect(screen.queryByTestId("archived-note")).toBeNull();
  });

  it("keeps the link in reach when every strategy is archived", async () => {
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([ARCHIVED]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    expect(await screen.findByText(en.strategies.empty)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: en.strategies.archivedToggle }));
    expect(await screen.findByText("Old Beta")).toBeInTheDocument();
  });
});

describe("the enable button asks first (owner, 2026-11-06)", () => {
  const patches = (api: ReturnType<typeof strategiesApi>) => api.calls.filter((call) => call.method === "PATCH");

  it("is a text button at the row's end: Disable in the loss tone on a running strategy, Enable in the gain tone on a stopped one, both as wide (L21)", async () => {
    const stopped = strategy({ id: "33333333-3333-4333-8333-333333333333", name: "Beta", enabled: false });
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([strategy(), stopped]).route);
    renderAt(<AppRoutes />, "/strategies/authored");

    const [alpha, beta] = await screen.findAllByTestId("strategy-row");
    const disable = within(alpha as HTMLElement).getByRole("button", { name: "Disable Alpha" });
    const enable = within(beta as HTMLElement).getByRole("button", { name: "Enable Beta" });
    expect(disable).toHaveTextContent(/^Disable$/);
    expect(enable).toHaveTextContent(/^Enable$/);
    expect(disable).toHaveClass("text-loss");
    expect(enable).toHaveClass("text-gain-bright");
    expect(disable).toHaveClass("w-24");
    expect(enable).toHaveClass("w-24");
    expect((alpha as HTMLElement).lastElementChild).toContainElement(disable);
  });

  it("pressed on an enabled strategy, asks to disable it, says what that does, and sends nothing yet", async () => {
    const api = strategiesApi([strategy()]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");
    const row = await screen.findByTestId("strategy-row");

    fireEvent.click(within(row).getByRole("button", { name: "Disable Alpha" }));

    const dialog = await screen.findByRole("dialog", { name: "Disable Alpha?" });
    expect(dialog).toHaveTextContent(en.strategies.enableDialog.disableBody.replace("{{name}}", "Alpha"));
    expect(within(row).getByTestId("strategy-enabled")).toHaveAccessibleName(en.strategies.detail.enabled);
    expect(patches(api)).toHaveLength(0);
  });

  it("pressed on a disabled strategy, asks to enable it", async () => {
    const api = strategiesApi([strategy({ enabled: false })]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");
    const row = await screen.findByTestId("strategy-row");

    fireEvent.click(within(row).getByRole("button", { name: "Enable Alpha" }));

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

    fireEvent.click(within(row).getByRole("button", { name: "Disable Alpha" }));
    await screen.findByRole("dialog");
    dismiss();

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(within(row).getByRole("button", { name: "Disable Alpha" })).toBeInTheDocument();
    expect(patches(api)).toHaveLength(0);
  });

  it("confirmed, sends the opposite value for that strategy and closes the question", async () => {
    const api = strategiesApi([strategy()]);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");
    const row = await screen.findByTestId("strategy-row");

    fireEvent.click(within(row).getByRole("button", { name: "Disable Alpha" }));
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

    fireEvent.click(within(row).getByRole("button", { name: "Disable Alpha" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: en.strategies.enableDialog.disable }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(en.strategies.row.toggleError);
  });
});

describe("the author's figures in the table", () => {
  /** A report with a deepest fall and a win count, so the four reported figures all have a value. */
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

  async function oneRow(overrides: Record<string, unknown> = {}, perf?: ExtraRoute) {
    const api = strategiesApi(
      [strategy(overrides)],
      perf ?? ((url) => Promise.resolve(jsonResponse(reportWithPairs(/([^/]+)$/.exec(url)?.[1] ?? "")))),
    );
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies/authored");
    return await screen.findByTestId("strategy-row");
  }

  it("writes the PnL in the pool's currency and every percentage with its sign: +5.2%, never the bare number (L21)", async () => {
    const row = await oneRow({ subscribers: 3, live_subscribers: 2, capital: "300" });
    await waitFor(() => expect(within(row).getByTestId("strategy-return")).toHaveTextContent(/^\+3\.4%$/));

    expect(within(row).getByTestId("strategy-pnl").textContent).toBe("+41.20");
    expect(within(row).getByTestId("strategy-deepest").textContent).toBe("-8.2%");
    // Wins over closed trades across the pairs, the rate and the count in one cell: 4 of 7.
    expect(within(row).getByTestId("strategy-winrate").textContent).toBe("57.1%");
    expect(within(row).getByTestId("strategy-wins").textContent).toBe("4/7");
    expect(within(row).getByTestId("strategy-winrate").closest("td")).toHaveTextContent(/^57\.1% · 4\/7$/);
    expect(within(row).getByTestId("strategy-subscribers").textContent).toBe("2");
    expect(within(row).getByTestId("strategy-capital").textContent).toBe("300.00");
  });

  it("colours a gain as a gain and a fall as a loss", async () => {
    const row = await oneRow();
    await waitFor(() => expect(within(row).getByTestId("strategy-return")).toHaveTextContent("+3.4%"));

    expect(within(row).getByTestId("strategy-pnl")).toHaveClass("text-gain");
    expect(within(row).getByTestId("strategy-return")).toHaveClass("text-gain");
    expect(within(row).getByTestId("strategy-deepest")).toHaveClass("text-loss");
  });

  it("shows a dash where there is no figure yet", async () => {
    const row = await oneRow({ capital: null }, () => Promise.resolve(jsonResponse(null, 404)));
    await waitFor(() => expect(within(row).getByTestId("strategy-return")).toHaveTextContent("—"));
    for (const id of ["strategy-return", "strategy-deepest", "strategy-winrate", "strategy-capital", "strategy-pnl"]) {
      expect(within(row).getByTestId(id).textContent).toBe("—");
    }
    expect(within(row).queryByTestId("strategy-wins")).toBeNull();
  });

  it("waits with an ellipsis while its report is on its way", async () => {
    const row = await oneRow({}, () => new Promise<Response>(() => undefined));
    for (const id of ["strategy-pnl", "strategy-return", "strategy-deepest", "strategy-winrate"]) {
      expect(within(row).getByTestId(id).textContent, id).toBe("…");
    }
  });

  it("shows no share of the strategy, no uptime and no settings: they are a seat's", async () => {
    const row = await oneRow({ subscription: subscriptionOf("11111111-1111-4111-8111-111111111111", "37.5") });
    await waitFor(() => expect(within(row).getByTestId("strategy-return")).toHaveTextContent("+3.4%"));
    expect(row.textContent).not.toContain("37.5");
    expect(row.textContent?.toLowerCase()).not.toContain("per trade");
    expect(within(row).queryByRole("slider")).toBeNull();
    expect(within(row).queryByTestId("strategy-uptime")).toBeNull();
  });

  it("blanks only a row's figures when its report fails, and says so once across them", async () => {
    const row = await oneRow({}, () => Promise.resolve(jsonResponse({ detail: "boom" }, 500)));
    const alert = await within(row).findByText(en.strategies.row.performanceError);
    expect(alert.closest("td")).toHaveAttribute("colspan", "4");
    expect(within(row).getByRole("link", { name: "Alpha" })).toBeInTheDocument();
    expect(within(row).queryByTestId("strategy-pnl")).toBeNull();
    // The columns after the figures are still there: subscribers, capital and the button.
    expect(within(row).getByTestId("strategy-subscribers")).toBeInTheDocument();
    expect(within(row).getAllByRole("cell")).toHaveLength(7);
  });

  it("makes the row's figures unreadable for a report without the win fields, and says so", async () => {
    const row = await oneRow({}, () =>
      Promise.resolve(
        jsonResponse({
          ...strategyReport("11111111-1111-4111-8111-111111111111"),
          by_pair: [{ pair: "SOLUSDT", trades: 7, pnl: "41.20", return: "0.0340000000" }],
        }),
      ),
    );
    expect(await within(row).findByText(en.strategies.row.performanceError)).toBeInTheDocument();
    expect(within(row).queryByTestId("strategy-pnl")).not.toBeInTheDocument();
  });

  it("no longer shows the open-state line above the list", async () => {
    const row = await oneRow();
    expect(row).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(en.positions.state.loading)).not.toBeInTheDocument());
    expect(screen.queryByText("Open:")).not.toBeInTheDocument();
    expect(screen.queryByText("Orders in flight:")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Read again" })).not.toBeInTheDocument();
  });
});

describe("the author's list is sorted by the figure the table shows", () => {
  const A = "a1a1a1a1-a1a1-41a1-81a1-a1a1a1a1a1a1";
  const B = "b1b1b1b1-b1b1-41b1-81b1-b1b1b1b1b1b1";
  const C = "c1c1c1c1-c1c1-41c1-81c1-c1c1c1c1c1c1";
  const rows = [
    strategy({ id: A, name: "Aaa", created_at: "2026-09-10T00:00:00Z", subscribers: 9, live_subscribers: 1, capital: "100" }),
    strategy({ id: B, name: "Bbb", created_at: "2026-08-10T00:00:00Z", subscribers: 6, live_subscribers: 5, capital: "50" }),
    strategy({ id: C, name: "Ccc", created_at: "2026-09-20T00:00:00Z", subscribers: 7, live_subscribers: 3, capital: "900" }),
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
    await waitFor(() => expect(screen.getAllByTestId("strategy-return").map((node) => node.textContent)).not.toContain("…"));
  }
  const press = (name: string) => fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${name}`) }));

  it("starts on return, largest first, the contribution to the pool", async () => {
    await mount();
    expect(names()).toEqual(["Bbb", "Ccc", "Aaa"]);
    expect(screen.getByRole("button", { name: /^Return/ })).toHaveAttribute("aria-pressed", "true");
  });

  it.each([
    ["Closed trades", ["Bbb", "Ccc", "Aaa"]],
    // By the live count the table shows, not by every seat: by seats it would be Aaa, Ccc, Bbb (L.11).
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

  it("a row whose figures failed sorts last both ways", async () => {
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

  const binanceStrategy = strategy({ id: BINANCE_ID, name: "Binance Strat", exchange: "binance", allowed_pairs: ["ONEUSDT"] });
  const bybitStrategy = strategy({ id: BYBIT_ID, name: "Bybit Strat", exchange: "bybit", allowed_pairs: ["TWOUSDT"] });

  it("draws only binance's strategies on the binance tab, then only bybit's", async () => {
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([binanceStrategy, bybitStrategy]).route);
    renderAt(<AppRoutes />, "/strategies/authored");
    // The scope starts on the first exchange (bybit); the owner moves to binance first.
    await screen.findByText("Bybit Strat");
    fireEvent.click(screen.getAllByRole("button", { name: "Binance" })[0] as HTMLElement);
    await screen.findByText("Binance Strat");

    const row = screen.getByTestId("strategy-row");
    expect(within(row).getByRole("link", { name: "Binance Strat" })).toBeInTheDocument();
    expect(within(row).getByTestId("strategy-pairs")).toHaveTextContent("ONEUSDT");
    expect(document.body.textContent ?? "").not.toContain("TWOUSDT");

    fireEvent.click(screen.getAllByRole("button", { name: "Bybit" })[0] as HTMLElement);
    await screen.findByText("Bybit Strat");
    expect(screen.getByTestId("strategy-row")).toHaveTextContent("TWOUSDT");
    expect(document.body.textContent ?? "").not.toContain("ONEUSDT");
  });

  it("counts the archived ones of the exchange on the tab alone", async () => {
    const archivedBinance = strategy({
      id: "b3b3b3b3-b3b3-43b3-83b3-b3b3b3b3b3b3",
      name: "Old Binance",
      exchange: "binance",
      archived_at: "2026-09-01T00:00:00Z",
    });
    stubApi(HEALTH, [], POOLS, {}, strategiesApi([bybitStrategy, binanceStrategy, archivedBinance, ARCHIVED]).route);
    renderAt(<AppRoutes />, "/strategies/authored");
    await screen.findByText("Bybit Strat");
    // ARCHIVED is a bybit strategy: one hidden here, and the binance one is not counted.
    expect(screen.getByTestId("archived-note")).toHaveTextContent("1 archived strategy is hidden.");

    fireEvent.click(screen.getAllByRole("button", { name: "Binance" })[0] as HTMLElement);
    await screen.findByText("Binance Strat");
    expect(screen.getByTestId("archived-note")).toHaveTextContent("1 archived strategy is hidden.");
    expect(screen.queryByText("Old Binance")).not.toBeInTheDocument();
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
      expect(locale.strategies.row.toggleError).toBeTruthy();
      expect(locale.strategies.row.performanceError).toBeTruthy();
      expect(locale.strategies.table.hideArchived).toBeTruthy();
    }
  });

  it("names the table's columns in Spanish as the approved prototype does (ex13)", () => {
    expect(es.strategies.table.head.drawdown).toBe("Caída máx.");
    expect(es.strategies.table.head.winRate).toBe("Acierto");
    expect(es.strategies.table.head.seat).toBe("Pool / Apal.");
    expect(es.strategies.table.disable).toBe("Desactivar");
    expect(es.strategies.table.enable).toBe("Activar");
  });
});
