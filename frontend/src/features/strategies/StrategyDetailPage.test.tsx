import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Link, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StrategyDetailPage } from "@/features/strategies/StrategyDetailPage";
import type { OpenPosition } from "@/shared/api/positions";
import type { EnablementEvent, PairStat, Strategy, StrategyTrade } from "@/shared/api/types";
import { useHiddenStore } from "@/shared/hidden/hidden-store";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { useExchangeStore } from "@/shared/scope/exchange-store";
import {
  emptyPerformance,
  jsonResponse,
  lock,
  openPosition,
  openState,
  pool,
  renderAt,
  resetExchangeScope,
  SIGNED_UP,
  strategyRoute,
  stubApi,
  subscriptionOf,
  unlock,
  unsyncedSharePreview,
} from "@/test/harness";

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
    subscription: subscriptionOf(ID),
    enabled: false,
    archived_at: null,
    allowed_pairs: ["ETHUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    visibility: "PRIVATE",
    share_token: null,
    secret_last4: "x4F2",
    description: null,
    subscribers: 1,
    live_subscribers: 0,
    created_at: null,
    capital: null,
    stop_loss_pct: "10.00",
    ...overrides,
  };
}

/** Two pairs that have traded: the By pair section is drawn only when more than one has. */
const TWO_PAIRS: PairStat[] = [
  { pair: "ETHUSDT", trades: 2, wins: 1, win_rate: "0.5000000000", pnl: "4.00", return: "0.0040000000" },
  { pair: "SOLUSDT", trades: 1, wins: 1, win_rate: "1.0000000000", pnl: "2.00", return: "0.0020000000" },
];

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
  /** Added to who is signed in: a `display_name`, for one. */
  me?: Record<string, unknown>;
  /** The positions `GET /positions/open` answers; none by default, so the Open positions card is not drawn (L39). */
  open?: OpenPosition[];
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
      if (url.endsWith("/api/me") && options.me !== undefined) {
        return Promise.resolve(
          jsonResponse({ email: "owner@example.com", is_admin: true, mode: "SIMULATION", dry_run_brake: true, ...SIGNED_UP, ...options.me }),
        );
      }
      if (url.includes(`/performance/strategies/${ID}/trades`)) {
        return Promise.resolve(jsonResponse({ trades: options.trades ?? [], next_cursor: null, total: (options.trades ?? []).length }));
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
      if (url.includes("/share-preview")) return Promise.resolve(jsonResponse(unsyncedSharePreview(ID)));
      if (url.endsWith("/events")) return Promise.resolve(jsonResponse(options.events ?? []));
      if (method === "PATCH") return Promise.resolve(options.patch?.(JSON.parse(String(init?.body))) ?? jsonResponse(subject));
      return Promise.resolve(options.strategyAnswer?.() ?? jsonResponse(subject));
    },
    {},
    undefined,
    options.open === undefined ? undefined : { kind: "ok", body: openState(options.open) },
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
  it("opens with the breadcrumb Home > Strategies > My strategies > the strategy, in place of a link back (S12)", async () => {
    renderPage();
    await heading("ETH Breakout");

    const trail = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(trail).getByRole("link", { name: "My strategies" })).toHaveAttribute("href", "/strategies/authored");
    expect(within(trail).getByText("ETH Breakout")).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("link", { name: i18n.t("strategies.detail.back") })).not.toBeInTheDocument();
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

  it("mounts the stop level editor on the strategy's own level", async () => {
    renderPage(strategy({ stop_loss_pct: "7.50" }));
    await heading("ETH Breakout");

    const region = screen.getByRole("region", { name: i18n.t("strategies.stopLevel.label") });
    expect(within(region).getByRole("textbox")).toHaveValue("7.5");
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
    expect(screen.getByRole("link", { name: i18n.t("strategies.detail.back") })).toHaveAttribute("href", "/strategies/authored");
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
    // It asks first (owner, 2026-11-06): nothing is sent until the question is confirmed.
    const dialog = await screen.findByRole("dialog", { name: "Disable ETH Breakout?" });
    expect(bodies).toEqual([]);
    fireEvent.click(within(dialog).getByRole("button", { name: i18n.t("strategies.enableDialog.disable") }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(i18n.t("strategies.row.toggleError"));
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
    // The strategy's `secret_last4` ("x4F2" in this file's fixture), after the mask.
    expect(screen.getByLabelText(en.strategies.webhook.urlLabel)).toHaveTextContent("/webhook/tradingview?secret=***x4F2");
    const deleteButton = screen.getByRole("button", { name: i18n.t("strategies.delete.button") });
    expect(message.compareDocumentPosition(deleteButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  // Was test_left_column_runs_performance_by_pair_trades_and_ends_with_the_webhook_block: the webhook block
  // left the column's end for a disclosure in the header (it supersedes the placement of 12f.8).
  // Renamed from test_left_column_runs_performance_by_pair_and_trades_and_holds_no_webhook_block_until_it_is_opened:
  // decision 43 moves the closed trades out of the column (task 9p.5.21), so its trades assertions moved to
  // the full-width section test below and the webhook assertion stayed.
  it("test_left_column_runs_performance_and_by_pair_and_holds_no_webhook_block_until_it_is_opened", async () => {
    renderPage(strategy(), { byPair: TWO_PAIRS });
    await heading("ETH Breakout");

    const titles = [
      await screen.findByRole("heading", { name: en.strategies.performance.byPair.title }),
      screen.getByRole("heading", { name: en.strategies.report.title }),
    ].reverse();
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

  it("frames the chart, Monthly performance, By pair, Open positions and Closed trades (owner decision 67 Q4, Q7)", async () => {
    renderPage(strategy(), { byPair: TWO_PAIRS, open: [openPosition({ strategy_id: ID })] });
    await heading("ETH Breakout");

    // Each table is a card of its own, as the prototype draws it (L30), never inside a framed section.
    for (const name of [
      en.strategies.performance.byPair.title,
      en.strategies.performance.trades.title,
      "Open positions",
    ]) {
      const card = await screen.findByRole("region", { name });
      expect(card.closest('[data-testid="report-section"]')).toBeNull();
    }
    // The chart is the one image inside a figure; the ledger's icons are images too.
    const chart = (await screen.findAllByRole("img", { name: /./ })).find((image) => image.closest("figure") !== null);
    // The chart sits in the Performance card, which is the frame the other report boxes have (L26).
    expect(screen.getByRole("region", { name: en.strategies.report.title })).toContainElement(chart?.closest("figure") as HTMLElement);
    // The months sit in the dashboard's own card (L29).
    const monthly = await screen.findByRole("region", { name: "Monthly performance" });
    expect(monthly.closest('[data-testid="report-section"]')).toBeNull();
  });

  it("puts the closed trades table in a full-width section under the two-column grid and above the delete control", async () => {
    renderPage(strategy());
    await heading("ETH Breakout");

    // The card is what sits under the grid (L30).
    const section = await screen.findByRole("region", { name: en.strategies.performance.trades.title });
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

    // The dry run is a dot beside the pair, named by its tag (L31).
    expect(within(table).queryByRole("img", { name: en.strategies.performance.trades.rehearsal })).toBeInTheDocument();
    // The sentence waits behind the (i) beside the title until it is clicked.
    expect(screen.queryByText(en.strategies.performance.trades.rehearsalNote)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: en.strategies.performance.trades.notesInfo }));
    expect(screen.queryByText(en.strategies.performance.trades.rehearsalNote)).toBeInTheDocument();
    expect(screen.queryByText(en.strategies.performance.trades.empty)).toBeNull();
    expect(screen.queryByText(en.strategies.performance.trades.rehearsalFixedNote)).toBeNull();
  });

  it("test_enable_history_sits_in_the_settings_column_below_the_enable_and_archive_row", async () => {
    renderPage(strategy(), { events: [{ enabled: true, occurred_at: "2026-08-12T10:00:00+00:00", origin: "OBSERVED" }] });
    await heading("ETH Breakout");

    const settings = screen.getByRole("complementary", { name: en.strategies.detail.settings });
    const history = await within(settings).findByRole("heading", { name: en.strategies.detail.history.title });
    const enableSwitch = within(settings).getByRole("button", { name: en.strategies.detail.enable });
    const archive = within(settings).getByRole("button", { name: en.strategies.archive.button });

    expect(enableSwitch.compareDocumentPosition(history) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(archive.compareDocumentPosition(history) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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

  // A strategy shared by its link or its codes shows them first, right under the heading (StrategySharing.test.tsx);
  // a public one shares nothing there, and the share control comes first.
  it("test_the_share_control_is_the_first_of_a_public_strategys_settings_column_under_its_heading_and_above_the_allowed_pairs", async () => {
    renderPage(strategy({ visibility: "PUBLIC", subscription: subscriptionOf(ID, "37.5") }));
    await heading("ETH Breakout");

    const settings = screen.getByRole("complementary", { name: en.strategies.detail.settings });
    const slider = within(settings).queryByRole("slider", { name: en.strategies.detail.share.label });
    expect(slider).toBeInTheDocument();

    const [header, first] = Array.from(settings.children) as [HTMLElement, HTMLElement];
    expect(header).toContainElement(within(settings).getByRole("heading", { level: 2, name: en.strategies.detail.settings }));
    expect(first).toContainElement(slider);
    expect(within(settings).getByRole("textbox", { name: en.strategies.detail.share.label })).toHaveValue("37.5");
    const pairs = within(settings).getByRole("list", { name: en.strategies.pairs.selected });
    expect(first).not.toContainElement(pairs);
    expect(first.compareDocumentPosition(pairs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("test_the_visibility_shares_the_settings_heading_row_above_every_other_setting", async () => {
    renderPage(strategy({ subscription: subscriptionOf(ID, "37.5") }));
    await heading("ETH Breakout");

    const settings = screen.getByRole("complementary", { name: en.strategies.detail.settings });
    const header = settings.children[0] as HTMLElement;
    expect(en.strategies.detail.settings).toBe("Strategy settings");
    expect(header).toContainElement(within(settings).getByRole("heading", { level: 2, name: "Strategy settings" }));
    expect(header).toContainElement(within(settings).getByRole("combobox", { name: en.strategies.visibility.label }));
  });

  it.each([
    ["PRIVATE", "lucide-lock", "lucide-globe"],
    ["PUBLIC", "lucide-globe", "lucide-lock"],
  ] as const)("test_a_%s_strategy_shows_its_icon_beside_the_visibility", async (visibility, shown, hidden) => {
    renderPage({ ...strategy({ subscription: subscriptionOf(ID, "37.5") }), visibility });
    await heading("ETH Breakout");

    const select = screen.getByRole("combobox", { name: en.strategies.visibility.label });
    const field = select.parentElement as HTMLElement;
    expect(field.querySelector(`svg.${shown}`)).not.toBeNull();
    expect(field.querySelector(`svg.${hidden}`)).toBeNull();
  });

  it("test_no_text_of_the_pages_header_line_contains_the_share_or_per_trade", async () => {
    renderPage(strategy({ subscription: subscriptionOf(ID, "37.5") }));
    const title = await heading("ETH Breakout");

    const header = title.closest("header") as HTMLElement;
    expect(header.textContent).not.toContain("37.5");
    expect(header.textContent).not.toContain("%");
    expect(header.textContent?.toLowerCase()).not.toContain("per trade");
    expect(header.textContent).not.toContain(en.strategies.detail.share.label);
  });

  it("test_the_leverage_control_follows_the_share_control_in_the_settings_column", async () => {
    renderPage(strategy({ subscription: subscriptionOf(ID, "37.5", { leverage: 4 }) }));
    await heading("ETH Breakout");

    const settings = screen.getByRole("complementary", { name: en.strategies.detail.settings });
    const share = within(settings).getByRole("slider", { name: en.strategies.detail.share.label });
    const leverage = within(settings).getByRole("slider", { name: en.strategies.leverage.label });
    expect(within(settings).getByRole("textbox", { name: en.strategies.leverage.label })).toHaveValue("4");
    expect(leverage).toHaveValue("4");
    expect(share.compareDocumentPosition(leverage) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const pairs = within(settings).getByRole("list", { name: en.strategies.pairs.selected });
    expect(leverage.compareDocumentPosition(pairs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const leverageRegion = within(settings).getByRole("region", { name: en.strategies.leverage.label });
    expect(within(leverageRegion).getByRole("button", { name: en.strategies.leverage.save })).toBeDisabled();
  });

  it("draws Connect a TradingView alert as New strategy and I have a code are drawn: the green outline (L40)", async () => {
    renderPage(strategy());
    await heading("ETH Breakout");

    const button = screen.getByRole("button", { name: en.strategies.webhook.open });
    expect(button).toHaveClass("h-10", "rounded-lg", "px-4", "border-gain/45", "text-gain-bright", "font-medium");
    expect(button).not.toHaveClass("border-rule", "text-ink");
  });

  it("draws the title above the two columns, so the settings start level with the header card (L40)", async () => {
    renderPage(strategy({ description: "Runs at 3x" }));
    const title = await heading("ETH Breakout");

    const settings = screen.getByRole("complementary", { name: en.strategies.detail.settings });
    const grid = settings.parentElement as HTMLElement;
    expect(grid).not.toContainElement(title);
    expect(title.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The header card is the first thing of the left column, beside the top of the settings.
    const column = grid.firstElementChild as HTMLElement;
    expect(column.firstElementChild).toContainElement(screen.getByTestId("strategy-description"));
  });

  it("puts Open positions in the left column, beside the settings, under the header card and above Performance (L37)", async () => {
    renderPage(strategy({ description: "Runs at 3x" }), { open: [openPosition({ strategy_id: ID })] });
    await heading("ETH Breakout");

    const positions = await screen.findByRole("region", { name: "Open positions" });
    const grid = screen.getByRole("complementary", { name: en.strategies.detail.settings }).parentElement as HTMLElement;
    expect(grid.firstElementChild).toContainElement(positions);
    const description = screen.getByTestId("strategy-description");
    const performance = screen.getByRole("heading", { level: 2, name: en.strategies.report.title });
    expect(description.compareDocumentPosition(positions) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(positions.compareDocumentPosition(performance) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows the description where the public page does, above Performance, and no editor in the settings column", async () => {
    renderPage(strategy({ description: "Runs at 3x\nNever above 5x" }));
    await heading("ETH Breakout");

    const section = screen.getByTestId("strategy-description");
    expect(within(section).getByRole("heading", { level: 2, name: en.strategies.description.publicHeading })).toBeInTheDocument();
    expect(section).toHaveTextContent("Runs at 3x");
    const performance = screen.getByRole("heading", { level: 2, name: en.strategies.report.title });
    expect(section.compareDocumentPosition(performance) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const settings = screen.getByRole("complementary", { name: en.strategies.detail.settings });
    expect(within(settings).queryByRole("textbox", { name: en.strategies.description.label })).not.toBeInTheDocument();
  });

  it("edits the description in place from its pencil, as the name: Save sends only the description and closes", async () => {
    const patched: unknown[] = [];
    renderPage(strategy({ description: "Runs at 3x" }), {
      patch: (body) => {
        patched.push(body);
        return jsonResponse(strategy({ description: "Runs at 5x" }));
      },
    });
    await heading("ETH Breakout");

    const section = screen.getByTestId("strategy-description");
    fireEvent.click(within(section).getByRole("button", { name: en.strategies.description.edit }));
    const field = within(section).getByRole("textbox", { name: en.strategies.description.label });
    expect(field).toHaveValue("Runs at 3x");
    expect(field).toHaveFocus();
    fireEvent.change(field, { target: { value: "Runs at 5x" } });
    fireEvent.click(within(section).getByRole("button", { name: en.strategies.description.save }));

    await waitFor(() => expect(patched).toEqual([{ description: "Runs at 5x" }]));
    await waitFor(() => expect(within(section).queryByRole("textbox")).not.toBeInTheDocument());
    expect(within(section).getByRole("button", { name: en.strategies.description.edit })).toHaveFocus();
  });

  it("leaves the description as it was on Cancel, and sends nothing", async () => {
    const patched: unknown[] = [];
    renderPage(strategy({ description: "Runs at 3x" }), {
      patch: (body) => {
        patched.push(body);
        return jsonResponse(strategy());
      },
    });
    await heading("ETH Breakout");

    const section = screen.getByTestId("strategy-description");
    fireEvent.click(within(section).getByRole("button", { name: en.strategies.description.edit }));
    fireEvent.change(within(section).getByRole("textbox"), { target: { value: "Something else" } });
    fireEvent.click(within(section).getByRole("button", { name: en.strategies.detail.name.cancel }));

    expect(within(section).queryByRole("textbox")).not.toBeInTheDocument();
    expect(section).toHaveTextContent("Runs at 3x");
    expect(patched).toEqual([]);
  });

  it("invites a description where there is none, from the same pencil", async () => {
    renderPage(strategy({ description: null }));
    await heading("ETH Breakout");

    const section = screen.getByTestId("strategy-description");
    expect(section).toHaveTextContent(en.strategies.description.none);
    expect(within(section).getByRole("button", { name: en.strategies.description.edit })).toBeInTheDocument();
  });

  it("offers no pencil on an archived strategy, whose description cannot change", async () => {
    renderPage(strategy({ archived_at: "2026-09-01T00:00:00+00:00", description: "Runs at 3x" }));
    await heading("ETH Breakout");

    const section = screen.getByTestId("strategy-description");
    expect(section).toHaveTextContent("Runs at 3x");
    expect(within(section).queryByRole("button", { name: en.strategies.description.edit })).not.toBeInTheDocument();
  });

  it("test_an_archived_strategy_shows_the_leverage_control_read_only", async () => {
    renderPage(strategy({ archived_at: "2026-09-01T00:00:00+00:00" }));
    await heading("ETH Breakout");
    expect(screen.getByRole("slider", { name: en.strategies.leverage.label })).toBeDisabled();
  });

  it("test_an_archived_strategy_shows_the_control_read_only", async () => {
    renderPage(strategy({ subscription: subscriptionOf(ID, "37.5"), archived_at: "2026-09-01T00:00:00+00:00" }));
    await heading("ETH Breakout");

    const settings = screen.getByRole("complementary", { name: en.strategies.detail.settings });
    const slider = within(settings).queryByRole("slider", { name: en.strategies.detail.share.label });
    expect(slider).toBeInTheDocument();
    expect(slider).toBeDisabled();
    expect(within(settings).getByRole("textbox", { name: en.strategies.detail.share.label })).toBeDisabled();
    expect(within(settings).getByRole("textbox", { name: en.strategies.detail.share.label })).toHaveValue("37.5");
    const shareRegion = within(settings).getByRole("region", { name: en.strategies.detail.share.label });
    expect(within(shareRegion).getByRole("button", { name: en.strategies.detail.share.save })).toBeDisabled();
    expect(within(settings).getByRole("button", { name: i18n.t("strategies.detail.share.stop", { value: 25 }) })).toBeDisabled();
  });

  it("test_the_share_control_starts_over_for_another_strategy_and_a_typed_value_is_not_carried_to_it", async () => {
    const OTHER = "22222222-2222-4222-8222-222222222222";
    const first = strategyRoute(ID, "ETH Breakout");
    const second = strategyRoute(OTHER, "SOL Trend");
    stubApi(HEALTH, [], undefined, {}, (url, init) => first(url, init) ?? second(url, init));
    renderAt(
      <Routes>
        <Route
          path="strategies/:strategyId"
          element={
            <>
              <Link to={`/strategies/${OTHER}`}>next strategy</Link>
              <StrategyDetailPage />
            </>
          }
        />
      </Routes>,
      `/strategies/${ID}`,
    );
    await heading("ETH Breakout");

    // Both strategies store 100. A value typed on the first, and an explanation opened on it, are its own.
    fireEvent.change(screen.getByRole("textbox", { name: en.strategies.detail.share.label }), { target: { value: "40" } });
    fireEvent.click(screen.getByRole("button", { name: en.strategies.detail.share.info }));
    expect(screen.getByRole("textbox", { name: en.strategies.detail.share.label })).toHaveValue("40");
    expect(screen.getByText(en.strategies.detail.share.hint)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("link", { name: "next strategy" }));
    await heading("SOL Trend");

    expect(screen.getByRole("textbox", { name: en.strategies.detail.share.label })).toHaveValue("100");
    expect(screen.queryByText(en.strategies.detail.share.hint)).toBeNull();
  });

  it("test_returning_to_a_cached_strategy_draws_one_of_each_editor", async () => {
    // Verifier A1: three sibling editors once shared one key, so switching to a strategy whose query was
    // already cached (no pending render in between) left the previous strategy's editors on screen.
    const OTHER = "22222222-2222-4222-8222-222222222222";
    const first = strategyRoute(ID, "ETH Breakout");
    const second = strategyRoute(OTHER, "SOL Trend");
    stubApi(HEALTH, [], undefined, {}, (url, init) => first(url, init) ?? second(url, init));
    renderAt(
      <Routes>
        <Route
          path="strategies/:strategyId"
          element={
            <>
              <Link to={`/strategies/${ID}`}>first strategy</Link>
              <Link to={`/strategies/${OTHER}`}>second strategy</Link>
              <StrategyDetailPage />
            </>
          }
        />
      </Routes>,
      `/strategies/${OTHER}`,
    );
    await heading("SOL Trend");
    fireEvent.click(screen.getByRole("link", { name: "first strategy" }));
    await heading("ETH Breakout");

    fireEvent.click(screen.getByRole("link", { name: "second strategy" }));
    await heading("SOL Trend");

    const settings = screen.getByRole("complementary", { name: en.strategies.detail.settings });
    expect(within(settings).getAllByRole("textbox", { name: en.strategies.detail.share.label })).toHaveLength(1);
    expect(within(settings).getAllByRole("slider", { name: en.strategies.leverage.label })).toHaveLength(1);
  });

  it("test_every_new_key_exists_in_both_languages", () => {
    const keys = (node: unknown, prefix: string): string[] =>
      typeof node === "object" && node !== null
        ? Object.entries(node).flatMap(([key, value]) => keys(value, `${prefix}.${key}`))
        : [prefix];
    const newKeys = (locale: typeof en) =>
      [
        ...keys(locale.strategies.detail.share, "strategies.detail.share"),
        ...keys(locale.strategies.detail.saved, "strategies.detail.saved"),
        ...["copyUrl", "copyMessage", "copied", "copyFailed", "hostUnset", "hostError"].map(
          (key) => `strategies.webhook.${key}`,
        ),
        ...keys(locale.strategies.performance.byPair.winRate, "strategies.performance.byPair.winRate"),
      ].sort();

    expect(newKeys(es)).toEqual(newKeys(en));
    // 28 share texts (with the subscription's not-active, leaving and none, the start hint and the notional
    // line), "Saved", six webhook texts and the Win rate heading.
    expect(newKeys(en)).toHaveLength(28 + 1 + 6 + 1);
    for (const key of newKeys(en)) {
      expect(i18n.exists(key, { lng: "en" })).toBe(true);
      // Without the fallback to English, so a Spanish key that was deleted is not found.
      expect(i18n.exists(key, { lng: "es", fallbackLng: [] })).toBe(true);
    }
  });

  it("test_the_owners_own_words_are_unchanged", () => {
    expect(en.strategies.detail.saved).toBe("Saved");
    expect(es.strategies.detail.saved).toBe("Guardado");
    expect(en.strategies.webhook.copied).toBe("Copied");
    expect(es.strategies.webhook.copied).toBe("Copiado");
  });

  it.each([
    ["en", "Win rate", "Share of the pool per trade", "Connect a TradingView alert", "Regenerate secret", "Copy message"],
    ["es", "% acierto", "Porcentaje del pool por operación", "Conectar una alerta de TradingView", "Regenerar el secreto", "Copiar mensaje"],
  ])(
    "test_the_new_texts_of_the_page_read_exactly_as_designed_in_%s",
    async (language, winRate, shareLabel, openWebhook, regenerate, copyMessage) => {
      await i18n.changeLanguage(language);
      renderPage(strategy(), { byPair: TWO_PAIRS });
      await heading("ETH Breakout");

      const table = await screen.findByRole("table", { name: i18n.t("strategies.performance.byPair.title") });
      expect(within(table).getByRole("columnheader", { name: winRate })).toBeInTheDocument();
      expect(screen.getByRole("slider", { name: shareLabel })).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: openWebhook }));
      expect(screen.getByRole("button", { name: regenerate })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: copyMessage })).toBeInTheDocument();
    },
  );

  it("renders in Spanish and has the same keys in both locales", async () => {
    await i18n.changeLanguage("es");
    renderPage(strategy({ created_at: "2026-08-12T10:00:00+00:00" }));

    expect(await screen.findByRole("link", { name: es.nav.authored })).toBeInTheDocument();
    expect(screen.getByTestId("strategy-age")).toHaveTextContent(/^12 ago 2026 – /);
    expect(screen.getByTestId("strategy-origin")).toHaveTextContent(es.strategies.subscriptions.yours);
    // Short enough to stay on one line beside the other titles at 1390 px (owner, 2026-11-17).
    expect(screen.getByTestId("strategy-group-profitable")).toHaveTextContent(/^Operaciones rentables/);
    expect(screen.getByTestId("strategy-group-return")).toHaveTextContent(/^Rendimiento/);

    const keys = (node: unknown, prefix = ""): string[] =>
      typeof node === "object" && node !== null
        ? Object.entries(node).flatMap(([key, value]) => keys(value, `${prefix}${key}.`))
        : [prefix];
    expect(keys(es.strategies).sort()).toEqual(keys(en.strategies).sort());
  });
});

describe("the own page reads like another author's (owner, 2026-11-17)", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("draws the title as the public page does: the same size, in a row as tall as its pencil", async () => {
    renderPage();

    const title = await heading("ETH Breakout");
    expect(title).toHaveClass("font-display", "text-[28px]", "font-semibold", "text-ink");
    expect(title.parentElement).toHaveClass("min-h-11");
  });

  it("names its author and dates it on the market line, as the cards do, and says nothing more under the title", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-17T12:00:00Z"));
    renderPage(
      strategy({
        created_at: "2026-10-12T09:00:00Z",
        enabled: true,
        uptime: { seconds: 3 * DAY, first_enabled_at: "2026-11-14T00:00:00Z", baseline: false },
        subscribers: 3,
        live_subscribers: 2,
        capital: "300",
      }),
      { me: { display_name: "Ana" } },
    );

    const header = (await heading("ETH Breakout")).closest("header") as HTMLElement;
    await waitFor(() => expect(within(header).getByTestId("strategy-origin")).toHaveTextContent(/^by Ana$/));
    const market = within(header).getByTestId("strategy-market");
    expect(market).toHaveTextContent(/^bybit · usdt-m · USDT/);
    expect(within(market).getByTestId("strategy-age")).toHaveTextContent(/^Oct 12, 2026 – Nov 17, 2026$/);
    expect(within(market).getByRole("img", { name: en.strategies.card.age })).toBeInTheDocument();
    // The days active, the subscribers and the capital lines are gone: the last two are AuM's, in the figures.
    expect(header).not.toHaveTextContent(/active/i);
    expect(within(header).queryByTestId("strategy-subscribers")).not.toBeInTheDocument();
    expect(within(header).queryByTestId("strategy-capital")).not.toBeInTheDocument();
    const aum = screen.getByTestId("strategy-group-aum");
    expect(within(aum).getByTestId("strategy-subscribers")).toHaveTextContent(/^2$/);
    expect(within(aum).getByTestId("strategy-capital")).toHaveTextContent(/^300\.00$/);
  });

  it("says the strategy is the reader's own while they have chosen no author name", async () => {
    renderPage();

    await heading("ETH Breakout");
    expect(screen.getByTestId("strategy-origin")).toHaveTextContent(en.strategies.subscriptions.yours);
  });

  it("keeps the Performance heading, the range selector and the chart, and draws no ledger line", async () => {
    renderPage(strategy(), { reportAnswer: () => jsonResponse(TRADED_REPORT) });
    await heading("ETH Breakout");

    await screen.findByTestId("return-curve");
    const performance = screen.getByRole("region", { name: en.strategies.report.title });
    expect(within(performance).getByRole("heading", { level: 2, name: en.strategies.report.title })).toBeInTheDocument();
    expect(within(performance).getByRole("button", { name: "30D" })).toBeInTheDocument();
    expect(within(performance).getByTestId("return-curve")).toBeInTheDocument();
    // The title is the card's own: nothing above the card repeats it (L26).
    expect(screen.getAllByRole("heading", { level: 2, name: en.strategies.report.title })).toHaveLength(1);
    expect(screen.queryByTestId("ledger-line")).not.toBeInTheDocument();
  });
});

/** A report with three closed trades (2 won across the two pairs), 41.25 USDT of PnL, 2 % of return, a 1 % fall. */
const TRADED_REPORT = {
  ...emptyPerformance("bybit", "usdt-m", "USDT"),
  strategy_id: ID,
  trade_count: 3,
  total_pnl: "41.25",
  curve: [{ date: new Date(Date.now() - 5 * 86_400_000).toISOString().slice(0, 10), daily_return: "0.02", index: "0.02", drawdown: "0" }],
  max_drawdown: "-0.0100000000",
  ranges: ["7D", "30D", "90D", "1Y", "All"].map((range) => ({ range, pnl: "41.25", return: "0.0200000000", trade_count: 3 })),
  by_pair: TWO_PAIRS,
};

describe("the header card (S14, RD.7b)", () => {
  const card = () => screen.findByTestId("strategy-header-card");

  it("holds About this strategy and the figure row, and comes before Performance", async () => {
    renderPage(strategy({ description: "Mean reversion on ETH." }), { reportAnswer: () => jsonResponse(TRADED_REPORT) });
    await heading("ETH Breakout");

    const header = await card();
    expect(within(header).getByRole("heading", { level: 2, name: en.strategies.description.publicHeading })).toBeInTheDocument();
    expect(within(header).getByTestId("strategy-description")).toHaveTextContent("Mean reversion on ETH.");
    const line = within(header).getByTestId("figure-line");
    const groups = [...line.children].map((group) => group.getAttribute("data-testid"));
    expect(groups).toEqual([
      "strategy-group-pnl",
      "strategy-group-return",
      "strategy-group-drawdown",
      "strategy-group-profitable",
      "strategy-group-aum",
    ]);
    // The description comes first inside the card, the figures under it.
    expect(
      within(header).getByTestId("strategy-description").compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    const performance = screen.getByRole("region", { name: en.strategies.report.title });
    expect(header.compareDocumentPosition(performance) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(performance).queryByTestId("figure-line")).not.toBeInTheDocument();
    expect(within(performance).queryByTestId("strategy-group-pnl")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("figure-line")).toHaveLength(1);
  });

  it("draws the PnL and the return apart, as the Panel does, then the fall, the profitable trades and the AuM (L42)", async () => {
    renderPage(strategy({ live_subscribers: 2, capital: "300" }), { reportAnswer: () => jsonResponse(TRADED_REPORT) });
    await heading("ETH Breakout");

    const header = await card();
    await waitFor(() => expect(within(header).getByTestId("strategy-pnl")).toHaveTextContent(/^\+41\.25USDT$/));
    const pnl = within(header).getByTestId("strategy-group-pnl");
    const values = Array.from((pnl.querySelector("dd") as HTMLElement).children).map((value) => value.getAttribute("data-testid"));
    expect(values).toEqual(["strategy-pnl"]);
    const ret = within(header).getByTestId("strategy-group-return");
    expect(ret.querySelector("dt")).toHaveTextContent(/^Return$/);
    expect(within(ret).getByTestId("strategy-return")).toHaveTextContent(/^\+2\.0%$/);
    expect(within(header).getByTestId("strategy-deepest")).toHaveTextContent(/^-1\.0%$/);
    expect(within(header).getByTestId("strategy-deepest")).toHaveClass("text-loss");
    // The rate and the wins on one line, the wins with no word after them (L42).
    const profitable = within(header).getByTestId("strategy-group-profitable");
    expect(profitable.querySelector("dt")).toHaveTextContent(/^Profitable trades$/);
    expect(within(header).getByTestId("strategy-winrate")).toHaveTextContent(/^66\.7%$/);
    expect(within(header).getByTestId("strategy-wins")).toHaveTextContent(/^2\/3$/);
    expect(profitable.querySelector("dd .block")).toBeNull();
    const aum = within(header).getByTestId("strategy-group-aum");
    expect(within(aum).getByTestId("strategy-capital")).toHaveTextContent(/^300\.00$/);
    expect(aum.querySelector("dd")).toHaveTextContent(/^300\.00USDT · 2$/);
    // The capital, its currency and the subscribers on one line (L42).
    expect(aum.querySelector("dd .block")).toBeNull();
    expect(within(aum).getByTestId("strategy-subscribers")).toHaveTextContent(/^2$/);
    // The capital keeps its (i); the return's belongs to a public record, not to the author's own report.
    expect(within(aum).getByRole("img", { name: en.strategies.public.capitalInfo })).toBeInTheDocument();
    expect(within(header).queryByRole("img", { name: en.strategies.public.returnInfo })).not.toBeInTheDocument();
  });

  it("stars the money while the balances are hidden and leaves the percentages and the counts", async () => {
    useHiddenStore.setState({ hidden: true });
    try {
      renderPage(strategy({ live_subscribers: 2, capital: "300" }), { reportAnswer: () => jsonResponse(TRADED_REPORT) });
      await heading("ETH Breakout");

      const header = await card();
      await waitFor(() => expect(within(header).getByTestId("strategy-return")).toHaveTextContent("+2.0%"));
      expect(within(header).getByTestId("strategy-pnl")).toHaveTextContent(/^\*{6}USDT$/);
      expect(within(header).getByTestId("strategy-capital")).toHaveTextContent(/^\*{6}$/);
      expect(header).not.toHaveTextContent("41.25");
      expect(header).not.toHaveTextContent("300.00");
      expect(within(header).getByTestId("strategy-deepest")).toHaveTextContent("-1.0%");
      expect(within(header).getByTestId("strategy-wins")).toHaveTextContent(/^2\/3$/);
      expect(within(header).getByTestId("strategy-subscribers")).toHaveTextContent(/^2$/);
    } finally {
      useHiddenStore.setState({ hidden: false });
    }
  });

  it("still follows the range selector and still edits the description from its pencil", async () => {
    const answer = {
      ...TRADED_REPORT,
      ranges: ["7D", "30D", "90D", "1Y", "All"].map((range) => ({
        range,
        pnl: range === "7D" ? "5.00" : "41.25",
        return: range === "7D" ? "0.0050000000" : "0.0200000000",
        trade_count: 3,
      })),
    };
    renderPage(strategy({ description: "Mean reversion on ETH." }), { reportAnswer: () => jsonResponse(answer) });
    await heading("ETH Breakout");

    const header = await card();
    await waitFor(() => expect(within(header).getByTestId("strategy-pnl")).toHaveTextContent("+41.25"));
    fireEvent.click(screen.getByRole("button", { name: "7D" }));
    expect(within(header).getByTestId("strategy-pnl")).toHaveTextContent(/^\+5\.00USDT$/);
    // The range selector names the range; the label does not repeat it, so five figures fit one row (L42).
    expect(within(header).getByTestId("strategy-group-pnl").querySelector("dt span")?.textContent).toBe("Total PnL");
    fireEvent.click(screen.getByRole("button", { name: "30D" }));

    fireEvent.click(within(header).getByRole("button", { name: en.strategies.description.edit }));
    expect(within(header).getByRole("textbox", { name: en.strategies.description.label })).toBeInTheDocument();
  });
});

describe("StrategyDetailPage settings column (L.7)", () => {
  const settingsColumn = () => screen.getByRole("complementary", { name: en.strategies.detail.settings });

  it("puts Disable and Archive in one row, both growing to fill it, Enable history below the row", async () => {
    renderPage(strategy({ enabled: false }), {
      events: [{ enabled: true, occurred_at: "2026-08-12T10:00:00+00:00", origin: "OBSERVED" }],
    });
    await heading("ETH Breakout");

    const settings = settingsColumn();
    const enable = within(settings).getByRole("button", { name: en.strategies.detail.enable });
    const archive = within(settings).getByRole("button", { name: en.strategies.archive.button });
    const row = enable.parentElement?.parentElement as HTMLElement;
    expect(row).toContainElement(archive);
    expect(row).toHaveClass("flex");
    expect(row).not.toHaveClass("flex-col");
    for (const button of [enable, archive]) {
      expect(button).toHaveClass("w-full");
      expect(button.parentElement).toHaveClass("flex-1");
    }
    const history = await within(settings).findByRole("heading", { name: en.strategies.detail.history.title });
    expect(row).not.toContainElement(history);
    expect(row.compareDocumentPosition(history) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("draws Archive in the danger style", async () => {
    renderPage(strategy({ enabled: false }));
    await heading("ETH Breakout");

    const archive = within(settingsColumn()).getByRole("button", { name: en.strategies.archive.button });
    expect(archive).toHaveClass("border-loss", "text-loss");
  });

  it("drops the hint paragraph and shows its text as Archive's tooltip while Archive is unavailable", async () => {
    renderPage(strategy({ enabled: true }));
    await heading("ETH Breakout");

    const archive = within(settingsColumn()).getByRole("button", { name: en.strategies.archive.button });
    expect(archive).toBeDisabled();
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(screen.queryAllByText(en.strategies.archive.disabledHint).filter((node) => node.tagName === "P")).toEqual([]);
    // A disabled button gets no pointer events, so the tip lives on its wrapper: hover and keyboard focus show it.
    const wrapper = archive.parentElement as HTMLElement;
    expect(wrapper).toHaveAttribute("tabindex", "0");
    fireEvent.mouseEnter(wrapper);
    expect(screen.getByRole("tooltip")).toHaveTextContent(en.strategies.archive.disabledHint);
    fireEvent.mouseLeave(wrapper);
    fireEvent.focus(wrapper);
    expect(screen.getByRole("tooltip")).toHaveTextContent(en.strategies.archive.disabledHint);
    // The reason also stays with the button for assistive technology.
    expect(archive).toHaveAccessibleDescription(en.strategies.archive.disabledHint);
  });

  it("shows no tooltip on Archive once it is available", async () => {
    renderPage(strategy({ enabled: false }));
    await heading("ETH Breakout");

    const archive = within(settingsColumn()).getByRole("button", { name: en.strategies.archive.button });
    expect(archive).toBeEnabled();
    fireEvent.mouseEnter(archive.parentElement as HTMLElement);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("lets a lone Disable take the whole row once the strategy is archived", async () => {
    renderPage(strategy({ archived_at: "2026-09-01T00:00:00+00:00" }));
    await heading("ETH Breakout");

    const enable = within(settingsColumn()).getByRole("button", { name: en.strategies.detail.enable });
    expect(enable).toHaveClass("w-full");
    expect(enable.parentElement).toHaveClass("flex-1");
  });

  it("is at least as tall as main leaves room for, from lg up (owner, 2026-11-17)", async () => {
    renderPage(strategy());
    await heading("ETH Breakout");

    // The viewport less the top bar (4rem and its 1 px rule) and main's padding (1.75rem above and below).
    expect(settingsColumn()).toHaveClass("lg:min-h-[calc(100dvh-9rem)]");
  });

  it("spaces the sections apart by more than a section spaces its own title, field and slider (owner, 2026-11-17)", async () => {
    renderPage(strategy());
    await heading("ETH Breakout");

    expect(settingsColumn()).toHaveClass("gap-4");
    // Share, leverage, stop level and allowed pairs: every column inside each, from the title down, steps 1.5.
    const sections = [
      screen.getByRole("textbox", { name: en.strategies.detail.share.label }).closest("section"),
      screen.getByRole("textbox", { name: en.strategies.leverage.label }).closest("section"),
      screen.getByRole("region", { name: en.strategies.stopLevel.label }),
      screen.getByRole("region", { name: en.strategies.detail.pairs.title }),
    ] as HTMLElement[];
    for (const section of sections) {
      const columns = [section, ...section.querySelectorAll<HTMLElement>(".flex-col")];
      const gaps = columns.map((column) => /(?:^|\s)gap-(\S+)/.exec(column.className)?.[1] ?? "none");
      expect(new Set(gaps), section.getAttribute("aria-label") ?? section.textContent?.slice(0, 30)).toEqual(new Set(["1.5"]));
    }
    // A slider's legend is as tall as its labels: its 44 px stops reach 16 px below it, into the gap-4 between
    // sections (or the share amount's own margin), instead of leaving 24 px of empty room under every slider.
    for (const stop of [
      screen.getByRole("button", { name: "Set the share to 25%" }),
      screen.getByRole("button", { name: "Set the leverage to x5" }),
    ]) {
      expect(stop).toHaveClass("size-11");
      expect(stop.parentElement).toHaveClass("h-6", "mb-1");
    }
  });

  it("says what the stop allows right under the leverage field, above its slider (owner, 2026-11-17)", async () => {
    renderPage(strategy({ stop_loss_pct: "10.00" }));
    await heading("ETH Breakout");

    // Short, as the owner worded it (2026-11-17): the cap and the stop that sets it.
    const note = screen.getByText("Max leverage x9 with a 10% stop");
    const field = screen.getByRole("textbox", { name: en.strategies.leverage.label });
    const slider = screen.getByRole("slider", { name: en.strategies.leverage.label });
    expect(field.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(note.compareDocumentPosition(slider) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
