import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StrategyDetailPage } from "@/features/strategies/StrategyDetailPage";
import type { EnablementEvent, PairStat, Strategy, StrategyTrade } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { useExchangeStore } from "@/shared/scope/exchange-store";
import { emptyPerformance, jsonResponse, lock, pool, renderAt, resetExchangeScope, stubApi, unlock } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const DAY = 86_400;
const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: ID,
    name: "ETH Breakout",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    allocation_percent: "100",
    enabled: false,
    archived_at: null,
    allowed_pairs: ["ETHUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    ...overrides,
  };
}

interface Options {
  /** `by_pair` of the strategy's report. */
  byPair?: PairStat[];
  /** What the trades endpoint answers for the first page. */
  trades?: StrategyTrade[];
  /** Replaces the performance report's answer. */
  reportAnswer?: () => Response;
  events?: EnablementEvent[];
  pools?: unknown[];
  strategyAnswer?: () => Response;
  patch?: (body: unknown) => Response;
}

function renderPage(subject: Strategy = strategy(), options: Options = {}) {
  const requests: Array<{ method: string; url: string }> = [];
  stubApi(
    HEALTH,
    [],
    { kind: "ok", body: options.pools ?? [pool("bybit", "usdt-m")] },
    {},
    (url, init) => {
      const method = init?.method ?? "GET";
      if (url.includes(`/performance/strategies/${ID}/trades`)) {
        return Promise.resolve(jsonResponse({ trades: options.trades ?? [], next_cursor: null }));
      }
      if (url.endsWith(`/performance/strategies/${ID}`)) {
        return Promise.resolve(
          options.reportAnswer?.() ??
            jsonResponse({
              ...emptyPerformance(subject.exchange, subject.venue, subject.settlement_currency),
              strategy_id: ID,
              by_pair: options.byPair ?? [],
            }),
        );
      }
      if (!url.includes(`/strategies/${ID}`)) return undefined;
      requests.push({ method, url });
      if (url.endsWith("/events")) return Promise.resolve(jsonResponse(options.events ?? []));
      if (method === "PATCH") return Promise.resolve(options.patch?.(JSON.parse(String(init?.body))) ?? jsonResponse(subject));
      return Promise.resolve(options.strategyAnswer?.() ?? jsonResponse(subject));
    },
  );
  renderAt(
    <Routes>
      <Route path="strategies" element={<p>the list</p>} />
      <Route path="strategies/:strategyId" element={<StrategyDetailPage />} />
    </Routes>,
    `/strategies/${ID}`,
  );
  return requests;
}

const heading = (name: string) => screen.findByRole("heading", { level: 1, name });

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

describe("StrategyDetailPage", () => {
  it("test_shows_active_x_days_since_first_activation_date", async () => {
    renderPage(
      strategy({ enabled: true, uptime: { seconds: 10 * DAY + 3_600, first_enabled_at: "2026-08-12T10:00:00+00:00", baseline: false } }),
    );

    await heading("ETH Breakout");

    expect(screen.getByText("active 10 days since Aug 12, 2026")).toBeInTheDocument();
  });

  it("says 'at least' when the first activation was written by a migration baseline", async () => {
    renderPage(
      strategy({ enabled: true, uptime: { seconds: 1 * DAY, first_enabled_at: "2026-08-12T10:00:00+00:00", baseline: true } }),
    );

    await heading("ETH Breakout");

    expect(screen.getByText("active at least 1 day, since at least Aug 12, 2026")).toBeInTheDocument();
  });

  it("test_never_enabled_shows_no_activation_date", async () => {
    renderPage(strategy());

    await heading("ETH Breakout");

    expect(screen.getByText(i18n.t("strategies.row.neverEnabled"))).toBeInTheDocument();
    expect(screen.queryByText(/since/)).toBeNull();
  });

  it("test_the_delete_control_is_rendered_below_the_archive_control_for_the_loaded_strategy", async () => {
    renderPage();
    await heading("ETH Breakout");

    const archive = screen.getByRole("button", { name: i18n.t("strategies.archive.button") });
    const remove = screen.getByRole("button", { name: i18n.t("strategies.delete.button") });
    expect(archive.compareDocumentPosition(remove) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    fireEvent.click(remove);
    expect(screen.getByRole("dialog", { name: i18n.t("strategies.delete.confirmTitle", { name: "ETH Breakout" }) })).toBeInTheDocument();
  });

  it("mounts the allowed-pairs editor on the strategy's own pairs", async () => {
    renderPage(strategy({ allowed_pairs: ["ETHUSDT", "SOLUSDT"] }));
    await heading("ETH Breakout");

    const chips = screen.getByRole("list", { name: i18n.t("strategies.pairs.selected") });
    expect(within(chips).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["ETHUSDT×", "SOLUSDT×"]);
  });

  it("says the strategy does not exist on a 404, and links back to the list", async () => {
    renderPage(strategy(), { strategyAnswer: () => jsonResponse({ detail: "no strategy" }, 404) });

    expect(await screen.findByText(i18n.t("strategies.detail.notFound"))).toBeInTheDocument();
    expect(screen.getByRole("link", { name: i18n.t("strategies.detail.back") })).toHaveAttribute("href", "/strategies");
    expect(screen.queryByRole("button", { name: i18n.t("strategies.delete.button") })).toBeNull();
  });

  it("says the strategy could not be loaded when the body is not a strategy", async () => {
    renderPage(strategy(), { strategyAnswer: () => jsonResponse({ id: ID }) });

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.detail.error"));
    expect(screen.queryByRole("button", { name: i18n.t("strategies.archive.button") })).toBeNull();
  });

  it("scopes the exchange tabs to the strategy's exchange", async () => {
    useExchangeStore.setState({ selected: "binance" });
    renderPage(strategy(), { pools: [pool("binance", "usdt-m"), pool("bybit", "usdt-m")] });
    await heading("ETH Breakout");

    await waitFor(() => expect(useExchangeStore.getState().selected).toBe("bybit"));
  });

  it("leaves the exchange tabs alone when the strategy's exchange has no pool", async () => {
    useExchangeStore.setState({ selected: "bybit" });
    renderPage(strategy({ exchange: "pionex" }), { pools: [pool("bybit", "usdt-m")] });
    await heading("ETH Breakout");

    expect(useExchangeStore.getState().selected).toBe("bybit");
  });

  it("enables and disables through PATCH and says when the change was refused", async () => {
    const bodies: unknown[] = [];
    renderPage(strategy({ enabled: true }), {
      patch: (body) => {
        bodies.push(body);
        return jsonResponse({ detail: "no" }, 409);
      },
    });
    await heading("ETH Breakout");

    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.detail.disable") }));

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.row.toggleError"));
    expect(bodies).toEqual([{ enabled: false }]);
  });

  it("is read-only once archived: status shown, nothing to enable or archive", async () => {
    renderPage(strategy({ archived_at: "2026-09-01T00:00:00+00:00" }));
    await heading("ETH Breakout");

    expect(screen.getByText(i18n.t("strategies.row.archived"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: i18n.t("strategies.detail.enable") })).toBeDisabled();
    expect(screen.queryByRole("button", { name: i18n.t("strategies.archive.button") })).toBeNull();
  });

  it("lists the enable history newest first and marks a baseline row", async () => {
    renderPage(strategy({ enabled: true }), {
      events: [
        { enabled: true, occurred_at: "2026-08-01T10:00:00+00:00", origin: "BASELINE" },
        { enabled: false, occurred_at: "2026-08-10T10:00:00+00:00", origin: "OBSERVED" },
        { enabled: true, occurred_at: "2026-08-12T10:00:00+00:00", origin: "OBSERVED" },
      ],
    });
    await heading("ETH Breakout");

    const history = await screen.findByRole("list", { name: i18n.t("strategies.detail.history.title") });
    const rows = within(history).getAllByRole("listitem").map((item) => item.textContent);
    expect(rows).toEqual([
      "Enabled · Aug 12, 2026",
      "Disabled · Aug 10, 2026",
      `Enabled · Aug 1, 2026 · ${i18n.t("strategies.detail.history.baseline")}`,
    ]);
  });

  it("test_the_history_list_has_a_fixed_max_height_scrolls_and_is_keyboard_reachable", async () => {
    renderPage(strategy(), { events: [{ enabled: true, occurred_at: "2026-08-12T10:00:00+00:00", origin: "OBSERVED" }] });
    await heading("ETH Breakout");

    const history = await screen.findByRole("list", { name: i18n.t("strategies.detail.history.title") });
    expect(history).toHaveClass("max-h-18", "overflow-y-auto");
    expect(history).toHaveAttribute("tabindex", "0");
    expect(history).not.toHaveClass("h-18");
  });

  it("says so when nothing was ever enabled or disabled", async () => {
    renderPage();
    expect(await screen.findByText(i18n.t("strategies.detail.history.empty"))).toBeInTheDocument();
  });

  it("says the history could not be read when its body is malformed, and the rest of the page still works", async () => {
    renderPage(strategy(), { events: [{ enabled: "yes" }] as unknown as EnablementEvent[] });

    expect(await screen.findByText(i18n.t("strategies.detail.history.error"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: i18n.t("strategies.archive.button") })).toBeEnabled();
  });

  it("shows the webhook message of the loaded strategy, with its id as signal_type, once it is opened from the header, above the delete control", async () => {
    renderPage();
    await heading("ETH Breakout");
    fireEvent.click(screen.getByRole("button", { name: en.strategies.webhook.open }));

    const message = screen.getByRole("group", { name: en.strategies.webhook.messageLabel });
    expect(JSON.parse(message.textContent ?? "")).toMatchObject({ signal_type: ID });
    expect(screen.getByText(`/webhook/tradingview?secret=${en.strategies.webhook.secretPlaceholder}`)).toBeInTheDocument();
    const deleteButton = screen.getByRole("button", { name: i18n.t("strategies.delete.button") });
    expect(message.compareDocumentPosition(deleteButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  // Was test_left_column_runs_performance_by_pair_trades_and_ends_with_the_webhook_block: the webhook block
  // left the column's end for a disclosure in the header (it supersedes the placement of 12f.8).
  // Renamed from test_left_column_runs_performance_by_pair_and_trades_and_holds_no_webhook_block_until_it_is_opened:
  // decision 43 moves the closed trades out of the column (task 9p.5.21), so its trades assertions moved to
  // the full-width section test below and the webhook assertion stayed.
  it("test_left_column_runs_performance_and_by_pair_and_holds_no_webhook_block_until_it_is_opened", async () => {
    renderPage(strategy(), {
      byPair: [{ pair: "ETHUSDT", trades: 2, wins: 1, win_rate: "0.5000000000", pnl: "4.00", return: "0.0040000000" }],
    });
    await heading("ETH Breakout");

    const titles = [
      await screen.findByRole("heading", { name: "Contribution to the pool, compounded" }),
      await screen.findByRole("heading", { name: en.strategies.performance.byPair.title }),
    ];
    const grid = screen.getByRole("complementary", { name: en.strategies.detail.settings }).parentElement as HTMLElement;
    const column = grid.firstElementChild as HTMLElement;
    for (const title of titles) expect(column).toContainElement(title);
    for (let index = 1; index < titles.length; index += 1) {
      const previous = titles[index - 1] as HTMLElement;
      const next = titles[index] as HTMLElement;
      expect(previous.compareDocumentPosition(next) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    // The webhook block is closed.
    expect(screen.queryByRole("heading", { name: en.strategies.webhook.title })).toBeNull();
    expect(screen.getByRole("button", { name: en.strategies.webhook.open })).toHaveAttribute("aria-expanded", "false");
  });

  it("puts the closed trades table in a full-width section under the two-column grid and above the delete control", async () => {
    renderPage(strategy());
    await heading("ETH Breakout");

    const tradesTitle = await screen.findByRole("heading", { name: en.strategies.performance.trades.title });
    const section = tradesTitle.closest("section") as HTMLElement;
    const aside = screen.getByRole("complementary", { name: en.strategies.detail.settings });
    const grid = aside.parentElement as HTMLElement;
    const column = grid.firstElementChild as HTMLElement;
    const deleteButton = screen.getByRole("button", { name: i18n.t("strategies.delete.button") });

    expect(grid).not.toContainElement(section);
    expect(column).not.toContainElement(section);
    // A sibling of the grid, after it and before the delete control.
    expect(section.parentElement).toBe(grid.parentElement);
    expect(grid.compareDocumentPosition(section) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(section.compareDocumentPosition(deleteButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows the operations and sentence 1 of a strategy that only ran in dry run, under a report of zero trades", async () => {
    const rehearsal: StrategyTrade = {
      allocation_id: "00000000-0000-4000-8000-000000000009",
      pair: "ETHUSDT",
      direction: "LONG",
      opened_at: "2026-09-29T10:00:00Z",
      closed_at: "2026-09-30T10:00:00Z",
      rehearsal: true,
      rehearsal_fill_price: "UNDETERMINED",
      base_currency: "ETH",
      entry_price: "1.000000000000000000",
      exit_price: "1.000000000000000000",
      size: "2.000000000000000000",
      fees: "0",
      other_fees: [],
      pnl: "0",
      capital_at_open: null,
      return: null,
      fees_complete: true,
    };
    // The report is the default empty one: trade_count 0 and an empty ledger.
    renderPage(strategy(), { trades: [rehearsal] });
    await heading("ETH Breakout");

    const table = await screen.findByRole("table", { name: en.strategies.performance.trades.title });

    expect(within(table).queryByText(en.strategies.performance.trades.rehearsal)).toBeInTheDocument();
    expect(screen.queryByText(en.strategies.performance.trades.rehearsalNote)).toBeInTheDocument();
    expect(screen.queryByText(en.strategies.performance.trades.empty)).toBeNull();
    expect(screen.queryByText(en.strategies.performance.trades.rehearsalFixedNote)).toBeNull();
  });

  it("test_enable_history_sits_in_the_settings_column_between_the_enable_switch_and_archive", async () => {
    renderPage(strategy(), { events: [{ enabled: true, occurred_at: "2026-08-12T10:00:00+00:00", origin: "OBSERVED" }] });
    await heading("ETH Breakout");

    const settings = screen.getByRole("complementary", { name: en.strategies.detail.settings });
    const history = await within(settings).findByRole("heading", { name: en.strategies.detail.history.title });
    const enableSwitch = within(settings).getByRole("button", { name: en.strategies.detail.enable });
    const archive = within(settings).getByRole("button", { name: en.strategies.archive.button });

    expect(enableSwitch.compareDocumentPosition(history) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(history.compareDocumentPosition(archive) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // It keeps its height cap, its scroll and its keyboard focus.
    const list = within(settings).getByRole("list", { name: en.strategies.detail.history.title });
    expect(list).toHaveClass("max-h-18", "overflow-y-auto");
    expect(list).toHaveAttribute("tabindex", "0");
  });

  it("test_a_pair_removed_from_the_allowed_pairs_is_still_listed_with_its_stats_on_the_page", async () => {
    renderPage(strategy({ allowed_pairs: ["ETHUSDT"] }), {
      byPair: [
        { pair: "ETHUSDT", trades: 19, wins: 12, win_rate: "0.6315789474", pnl: "52.60", return: "0.0526000000" },
        { pair: "SOLUSDT", trades: 24, wins: 9, win_rate: "0.3750000000", pnl: "-5.30", return: "-0.0053000000" },
      ],
    });
    await heading("ETH Breakout");

    const table = await screen.findByRole("table", { name: en.strategies.performance.byPair.title });

    const removed = within(within(table).getByRole("row", { name: /^SOLUSDT/ }));
    expect(removed.getByText("24")).toBeInTheDocument();
    expect(removed.getByText("-5.30")).toBeInTheDocument();
  });

  it("lists this strategy's closed trades in its pool's currency", async () => {
    const trade: StrategyTrade = {
      allocation_id: "00000000-0000-4000-8000-000000000001",
      pair: "BTCUSD",
      direction: "SHORT",
      opened_at: "2026-09-29T10:00:00Z",
      closed_at: "2026-09-30T10:00:00Z",
      rehearsal: false,
      rehearsal_fill_price: null,
      base_currency: "BTC",
      entry_price: "0.451200000000000000",
      exit_price: "0.463100000000000000",
      size: "1250.000000000000000000",
      fees: "0.63",
      other_fees: [],
      pnl: "0.00120000",
      capital_at_open: null,
      return: null,
      fees_complete: true,
    };
    renderPage(strategy({ settlement_currency: "BTC" }), { trades: [trade] });
    await heading("ETH Breakout");

    const table = await screen.findByRole("table", { name: en.strategies.performance.trades.title });

    expect(within(table).getByRole("columnheader", { name: "PnL BTC" })).toBeInTheDocument();
    expect(within(table).getByText("+0.00120000")).toBeInTheDocument();
    expect(within(table).getByText("BTCUSD")).toBeInTheDocument();
  });

  it("keeps the settings and the controls when the performance report fails, and says so", async () => {
    renderPage(strategy(), { reportAnswer: () => jsonResponse({ detail: "boom" }, 500) });
    await heading("ETH Breakout");

    expect(await screen.findByText(en.strategies.performance.error)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: i18n.t("strategies.archive.button") })).toBeEnabled();
    expect(screen.getByRole("button", { name: en.strategies.webhook.open })).toBeEnabled();
  });

  it("test_the_share_control_is_the_first_of_the_settings_column_under_its_heading_and_above_the_allowed_pairs", async () => {
    renderPage(strategy({ allocation_percent: "37.5" }));
    await heading("ETH Breakout");

    const settings = screen.getByRole("complementary", { name: en.strategies.detail.settings });
    const slider = within(settings).queryByRole("slider", { name: en.strategies.detail.share.label });
    expect(slider).toBeInTheDocument();

    const [title, first] = Array.from(settings.children) as HTMLElement[];
    expect(title).toBe(within(settings).getByRole("heading", { level: 2, name: en.strategies.detail.settings }));
    expect(first).toContainElement(slider);
    expect(within(settings).getByRole("textbox")).toHaveValue("37.5");
    const pairs = within(settings).getByRole("list", { name: en.strategies.pairs.selected });
    expect(first).not.toContainElement(pairs);
    expect(first.compareDocumentPosition(pairs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("test_no_text_of_the_pages_header_line_contains_the_share_or_per_trade", async () => {
    renderPage(strategy({ allocation_percent: "37.5" }));
    const title = await heading("ETH Breakout");

    const header = title.closest("header") as HTMLElement;
    expect(header.textContent).not.toContain("37.5");
    expect(header.textContent).not.toContain("%");
    expect(header.textContent?.toLowerCase()).not.toContain("per trade");
    expect(header.textContent).not.toContain(en.strategies.detail.share.label);
  });

  it("test_an_archived_strategy_shows_the_control_read_only", async () => {
    renderPage(strategy({ allocation_percent: "37.5", archived_at: "2026-09-01T00:00:00+00:00" }));
    await heading("ETH Breakout");

    const settings = screen.getByRole("complementary", { name: en.strategies.detail.settings });
    const slider = within(settings).queryByRole("slider", { name: en.strategies.detail.share.label });
    expect(slider).toBeInTheDocument();
    expect(slider).toBeDisabled();
    expect(within(settings).getByRole("textbox")).toBeDisabled();
    expect(within(settings).getByRole("textbox")).toHaveValue("37.5");
    expect(within(settings).getByRole("button", { name: en.strategies.detail.share.save })).toBeDisabled();
    expect(within(settings).getByRole("button", { name: i18n.t("strategies.detail.share.stop", { value: 25 }) })).toBeDisabled();
  });

  it("renders in Spanish and has the same keys in both locales", async () => {
    await i18n.changeLanguage("es");
    renderPage(strategy({ uptime: { seconds: 2 * DAY, first_enabled_at: "2026-08-12T10:00:00+00:00", baseline: false } }));

    expect(await screen.findByRole("link", { name: es.strategies.detail.back })).toBeInTheDocument();
    expect(screen.getByText("activa 2 días desde el 12 ago 2026")).toBeInTheDocument();

    const keys = (node: unknown, prefix = ""): string[] =>
      typeof node === "object" && node !== null
        ? Object.entries(node).flatMap(([key, value]) => keys(value, `${prefix}${key}.`))
        : [prefix];
    expect(keys(es.strategies).sort()).toEqual(keys(en.strategies).sort());
  });
});
