import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import type { OpenPosition } from "@/shared/api/positions";
import type { CloseCause, MyTrade, TradeStrategyChoice } from "@/shared/api/trades";
import { useHiddenStore } from "@/shared/hidden/hidden-store";
import i18n from "@/shared/i18n";
import {
  jsonResponse,
  openPosition,
  openState,
  renderAt,
  resetExchangeScope,
  setViewport,
  stubApi,
  unlock,
} from "@/test/harness";

const DAY = 24 * 3600 * 1000;
const NOW = Date.now();
const ALPHA = "11111111-1111-4111-8111-111111111111";
const BETA = "22222222-2222-4222-8222-222222222222";

let sequence = 0;

/** A closed operation of `GET /performance/trades`, newest first when `hoursAgo` grows with the index. */
function closed(overrides: Partial<MyTrade> & { hoursAgo?: number } = {}): MyTrade {
  sequence += 1;
  const { hoursAgo = sequence, ...rest } = overrides;
  return {
    allocation_id: `00000000-0000-4000-8000-${String(sequence).padStart(12, "0")}`,
    strategy_id: ALPHA,
    strategy_name: "Alpha",
    strategy_archived: false,
    strategy_page: "AUTHORED",
    exchange: "bybit",
    venue: "usdt-m",
    currency: "USDT",
    pair: "SOLUSDT",
    direction: "LONG",
    opened_at: new Date(NOW - (hoursAgo + 5) * 3600e3).toISOString(),
    closed_at: new Date(NOW - hoursAgo * 3600e3).toISOString(),
    rehearsal: false,
    entry_price: "100.5",
    exit_price: "110",
    pnl: "5.5",
    fees_complete: true,
    close_cause: "SIGNAL",
    ...rest,
  };
}

/** An open position, opened `hoursAgo` hours back. */
function opened(hoursAgo: number, overrides: Partial<OpenPosition> = {}): OpenPosition {
  return openPosition({
    opened_at: new Date(NOW - hoursAgo * 3600e3).toISOString(),
    unrealized_pnl: "41.2",
    ...overrides,
  });
}

interface Served {
  open?: OpenPosition[];
  closed?: MyTrade[];
  strategies?: TradeStrategyChoice[];
  exchanges?: string[];
}

interface Asked {
  limit: string | null;
  offset: string | null;
  closed_since: string | null;
  strategy_id: string | null;
  exchange: string | null;
}

/** A fake server that honours the filters, the offset and the limit, and records every read of the trades. */
function serve({ open = [], closed: rows = [], strategies = [], exchanges = [] }: Served) {
  const asked: Asked[] = [];
  stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) => {
    if (!url.includes("/performance/trades")) return undefined;
    const params = new URL(url, "http://x").searchParams;
    const query: Asked = {
      limit: params.get("limit"),
      offset: params.get("offset"),
      closed_since: params.get("closed_since"),
      strategy_id: params.get("strategy_id"),
      exchange: params.get("exchange"),
    };
    asked.push(query);
    const passing = rows.filter(
      (row) =>
        (query.strategy_id === null || row.strategy_id === query.strategy_id) &&
        (query.exchange === null || row.exchange === query.exchange) &&
        (query.closed_since === null || Date.parse(row.closed_at) >= Date.parse(query.closed_since)),
    );
    const offset = Number(query.offset);
    return Promise.resolve(
      jsonResponse({
        trades: passing.slice(offset, offset + Number(query.limit)),
        total: passing.length,
        strategies,
        exchanges,
      }),
    );
  }, {}, undefined, { kind: "ok", body: openState(open) });
  return asked;
}

function open() {
  renderAt(<AppRoutes />, "/trades");
}

const rows = () => screen.queryAllByTestId("my-trade-row");
const cellsOf = (row: HTMLElement) => within(row).getAllByRole("cell");
const textsOf = (row: HTMLElement) => cellsOf(row).map((cell) => cell.textContent ?? "");
/** Column indexes of the table. */
const COL = { opened: 0, closed: 1, strategy: 2, pair: 3, side: 4, exchange: 5, entry: 6, exit: 7, pnl: 8 };

function tipOf(trigger: HTMLElement): string | null {
  fireEvent.mouseEnter(trigger);
  const text = screen.getByRole("tooltip").textContent;
  fireEvent.mouseLeave(trigger);
  return text;
}

async function loaded() {
  await screen.findAllByTestId("my-trade-row");
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
  setViewport("wide");
  useHiddenStore.setState({ hidden: false });
  sequence = 0;
});

afterEach(async () => {
  vi.unstubAllGlobals();
  useHiddenStore.setState({ hidden: false });
  await i18n.changeLanguage("en");
});

describe("My trades: the list", () => {
  it("lists the open operations first, newest opening first, then the closed ones newest close first (L55)", async () => {
    serve({
      open: [opened(30, { markets: ["OLDUSDT"] }), opened(2, { markets: ["NEWUSDT"] })],
      closed: [closed({ hoursAgo: 10, pair: "FIRSTUSDT" }), closed({ hoursAgo: 20, pair: "SECONDUSDT" })],
    });
    open();

    await loaded();
    const pairs = rows().map((row) => textsOf(row)[COL.pair]);
    expect(pairs).toEqual(["NEWUSDT", "OLDUSDT", "FIRSTUSDT", "SECONDUSDT"]);
    expect(rows().map((row) => row.getAttribute("data-kind"))).toEqual(["open", "open", "closed", "closed"]);
    expect(screen.getByRole("columnheader", { name: "Opened (UTC)" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Closed (UTC)" })).toBeInTheDocument();
    for (const head of ["Strategy", "Pair", "Side", "Exchange", "Entry", "Exit", "PnL USDT"]) {
      expect(screen.getByRole("columnheader", { name: head })).toBeInTheDocument();
    }
  });

  it("counts open and closed together, in one chip, and pages them as one list of 20 (L55)", async () => {
    serve({ open: [opened(1), opened(2)], closed: Array.from({ length: 43 }, () => closed()) });
    open();

    await loaded();
    expect(screen.getByTestId("my-trades-count")).toHaveTextContent("45 trades");
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    expect(rows()).toHaveLength(20);
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  });

  it("asks the closed ones for the rows the page has left after the open ones, across the seam (L55)", async () => {
    const asked = serve({
      open: Array.from({ length: 25 }, (_, index) => opened(index + 1)),
      closed: Array.from({ length: 30 }, () => closed()),
    });
    open();

    // Page 1 is all open: the closed ones are asked for their count alone.
    await screen.findByText("Page 1 of 3");
    expect(screen.getByTestId("my-trades-count")).toHaveTextContent("55 trades");
    expect(rows().every((row) => row.getAttribute("data-kind") === "open")).toBe(true);
    expect(asked.at(-1)).toMatchObject({ limit: "1", offset: "0" });

    // Page 2: the last 5 open ones, then the first 15 closed ones.
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(rows().filter((row) => row.getAttribute("data-kind") === "closed")).toHaveLength(15));
    expect(rows().filter((row) => row.getAttribute("data-kind") === "open")).toHaveLength(5);
    expect(asked.at(-1)).toMatchObject({ limit: "15", offset: "0" });

    // Page 3: closed only, from the 16th.
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(asked.at(-1)).toMatchObject({ limit: "20", offset: "15" }));
    await screen.findByText("Page 3 of 3");
    await waitFor(() => expect(rows()).toHaveLength(15));
    expect(rows().every((row) => row.getAttribute("data-kind") === "closed")).toBe(true);
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });
});

describe("My trades: the open rows", () => {
  it("says Open in the Closed column, has no exit, and its PnL is the unrealized one, with the tip (L53)", async () => {
    serve({ open: [opened(2, { unrealized_pnl: "41.2", entry_price: "96420.5" })] });
    open();

    const row = await screen.findByTestId("my-trade-row");
    const cells = textsOf(row);
    expect(cells[COL.closed]).toBe("Open");
    expect(cells[COL.exit]).toBe("—");
    expect(cells[COL.entry]).toBe("96420.5");
    expect(cells[COL.pnl]).toBe("+41.20");
    expect(cellsOf(row)[COL.pnl]).toHaveClass("text-gain");
    expect(tipOf(within(row).getByTestId("my-trade-pnl-tip"))).toBe("Unrealized, at the last price");
  });

  it("shows a dash for an unrealized PnL the server did not know, never a zero", async () => {
    serve({ open: [opened(2, { unrealized_pnl: null })] });
    open();

    const row = await screen.findByTestId("my-trade-row");
    expect(textsOf(row)[COL.pnl]).toBe("—");
  });

  it("puts the warning triangle in the Pair of an open row the exchange disagrees with, and the dot of its origin otherwise", async () => {
    serve({
      open: [
        opened(1, { markets: ["BADUSDT"], figures_missing: "UNRESOLVED_SYMBOL" }),
        opened(2, { markets: ["GOODUSDT"] }),
        opened(3, { markets: ["SIMUSDT"], origin: "rehearsal" }),
      ],
    });
    open();

    const [bad, good, sim] = await screen.findAllByTestId("my-trade-row");
    const pairCell = (row: HTMLElement | undefined) => cellsOf(row as HTMLElement)[COL.pair] as HTMLElement;
    expect(pairCell(bad).querySelector("svg.lucide-triangle-alert")).not.toBeNull();
    expect(pairCell(bad).querySelector("[data-dot]")).toBeNull();
    expect(pairCell(good).querySelector("svg.lucide-triangle-alert")).toBeNull();
    expect(pairCell(good).querySelector("[data-dot]")).toHaveClass("bg-gain");
    expect(pairCell(sim).querySelector("[data-dot]")).toHaveClass("bg-decision");
  });
});

describe("My trades: the closed rows", () => {
  it("draws a live operation's dot in gain and a rehearsal's in amber, each with its tip (L53)", async () => {
    serve({ closed: [closed({ pair: "LIVEUSDT" }), closed({ pair: "SIMUSDT", rehearsal: true })] });
    open();

    const [live, sim] = await screen.findAllByTestId("my-trade-row");
    const pairCell = (row: HTMLElement | undefined) => cellsOf(row as HTMLElement)[COL.pair] as HTMLElement;
    expect(pairCell(live).querySelector("[data-dot]")).toHaveClass("bg-gain");
    expect(pairCell(sim).querySelector("[data-dot]")).toHaveClass("bg-decision");
    expect(tipOf(pairCell(sim).querySelector("[role=img]") as HTMLElement)).toBe("Dry run");
    // A closed row never carries the triangle.
    expect(sim?.querySelector("svg.lucide-triangle-alert")).toBeNull();
  });

  it.each<[CloseCause, string, string, string]>([
    ["STOP_FIRED", "lucide-shield", "text-loss", "The stop fired at the exchange"],
    ["STOP_FAILED_CLOSED", "lucide-shield-alert", "text-loss", "Safety close: the stop could not be confirmed"],
    [
      "STRATEGY_STOPPED_CLOSED",
      "lucide-shield-alert",
      "text-loss",
      "Safety close: the strategy was disabled with the trade open",
    ],
    ["MANUAL_CLOSE", "lucide-user", "text-ink-3", "Closed manually"],
  ])("marks a %s close with %s, in %s, and tells it in a tip", async (cause, icon, tone, tip) => {
    serve({ closed: [closed({ close_cause: cause })] });
    open();

    const row = await screen.findByTestId("my-trade-row");
    const mark = within(row).getByTestId("my-trade-close-mark");
    expect(mark).toHaveAccessibleName(tip);
    expect(mark).toHaveClass(tone);
    expect(mark.querySelector("svg")).toHaveClass(icon);
    expect(mark.querySelector("svg")).toHaveClass("size-3.5");
    expect(tipOf(mark.parentElement as HTMLElement)).toBe(tip);
  });

  it("leaves a signal close with an empty slot of the same width, so every time starts at the same place", async () => {
    serve({ closed: [closed({ close_cause: "SIGNAL" }), closed({ close_cause: "STOP_FIRED" })] });
    open();

    const [signal, stop] = await screen.findAllByTestId("my-trade-row");
    expect(within(signal as HTMLElement).queryByTestId("my-trade-close-mark")).toBeNull();
    for (const row of [signal, stop]) {
      const slot = within(row as HTMLElement).getByTestId("my-trade-close-slot");
      expect(slot).toHaveClass("w-3.5");
    }
  });

  it("holds the slot and the time in a block flex, so the time keeps the opening time's line (an inline one lifts it)", async () => {
    serve({ closed: [closed({ close_cause: "STOP_FIRED" })] });
    open();

    const row = await screen.findByTestId("my-trade-row");
    const holder = within(row).getByTestId("my-trade-close-slot").parentElement;
    expect(holder).toHaveClass("flex");
    expect(holder).not.toHaveClass("inline-flex");
  });

  it("writes the PnL with its tone, the exit price, the side in words and the exchange by its name", async () => {
    serve({
      closed: [closed({ pnl: "-31.8", exit_price: "171.55", direction: "SHORT", exchange: "binance" })],
    });
    open();

    const row = await screen.findByTestId("my-trade-row");
    const cells = textsOf(row);
    expect(cells[COL.pnl]).toBe("-31.80");
    expect(cellsOf(row)[COL.pnl]).toHaveClass("text-loss");
    expect(cells[COL.exit]).toBe("171.55");
    expect(cells[COL.side]).toBe("Short");
    expect(cells[COL.exchange]).toBe("Binance");
    expect(cells[COL.closed]).toMatch(/\d{1,2}:\d{2}$/);
  });
});

describe("My trades: the strategy", () => {
  it("links the name to the page the server says the user can open, and leaves it plain when there is none", async () => {
    serve({
      closed: [
        closed({ strategy_name: "Mine", strategy_page: "AUTHORED", strategy_id: ALPHA }),
        closed({ strategy_name: "Listed", strategy_page: "LISTED", strategy_id: BETA }),
        closed({ strategy_name: "Gone", strategy_page: null }),
      ],
    });
    open();

    await loaded();
    expect(screen.getByRole("link", { name: "Mine" })).toHaveAttribute("href", `/strategies/${ALPHA}`);
    expect(screen.getByRole("link", { name: "Listed" })).toHaveAttribute("href", `/strategies/explore/${BETA}`);
    expect(screen.getByText("Gone")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Gone" })).toBeNull();
  });

  it("links an open row's strategy the same way", async () => {
    serve({ open: [opened(1, { strategy_name: "Openly", strategy_page: "LISTED", strategy_id: BETA })] });
    open();

    await loaded();
    expect(screen.getByRole("link", { name: "Openly" })).toHaveAttribute("href", `/strategies/explore/${BETA}`);
  });

  it("caps the name's width and cuts a longer one with an ellipsis, so a long name cannot push the table into cards (L56)", async () => {
    serve({ closed: [closed({ strategy_name: "Momentum Breakout Long/Short 4h", strategy_page: "AUTHORED", strategy_id: ALPHA })] });
    open();

    await loaded();
    expect(screen.getByRole("link", { name: "Momentum Breakout Long/Short 4h" })).toHaveClass("max-w-44", "truncate");
  });

  it("tells a cut name whole in a tip, and gives a name that fits none (L56)", async () => {
    const width = (cut: number, whole: number) =>
      function (this: HTMLElement) {
        return this.dataset.testid === "my-trade-strategy-name" ? (this.textContent === "Long enough to be cut" ? cut : whole) : 0;
      };
    const scroll = vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockImplementation(width(260, 120));
    const client = vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(width(192, 120));
    try {
      serve({ closed: [closed({ strategy_name: "Long enough to be cut", strategy_page: null }), closed({ strategy_name: "Short", strategy_page: null })] });
      open();

      await loaded();
      expect(tipOf(screen.getByText("Long enough to be cut"))).toBe("Long enough to be cut");
      fireEvent.mouseEnter(screen.getByText("Short"));
      expect(screen.queryByRole("tooltip")).toBeNull();
    } finally {
      scroll.mockRestore();
      client.mockRestore();
    }
  });
});

describe("My trades: the PnL column across currencies (rule 7)", () => {
  it("names the currency in the heading when every row on the page shares one", async () => {
    serve({ open: [opened(1)], closed: [closed()] });
    open();

    await loaded();
    expect(screen.getByRole("columnheader", { name: "PnL USDT" })).toBeInTheDocument();
    expect(textsOf(rows()[1] as HTMLElement)[COL.pnl]).toBe("+5.50");
  });

  it("heads it PnL alone and writes each amount with its own currency when the page mixes them", async () => {
    serve({ closed: [closed({ pnl: "5.5" }), closed({ pnl: "0.00012", currency: "BTC", exchange: "binance" })] });
    open();

    await loaded();
    expect(screen.getByRole("columnheader", { name: "PnL" })).toBeInTheDocument();
    const [usdt, btc] = rows();
    expect(textsOf(usdt as HTMLElement)[COL.pnl]).toBe("+5.50 USDT");
    expect(textsOf(btc as HTMLElement)[COL.pnl]).toBe("+0.00012000 BTC");
  });
});

describe("My trades: the filters", () => {
  it("asks for the last 30 days by default, and for 7, 90 days or all when told", async () => {
    const asked = serve({ closed: [closed()] });
    open();
    await loaded();

    const sinceDays = (query: Asked | undefined) =>
      query?.closed_since == null ? null : Math.round((NOW - Date.parse(query.closed_since)) / DAY);
    expect(sinceDays(asked.at(-1))).toBe(30);
    const period = screen.getByRole("combobox", { name: "Period" });
    expect(period).toHaveValue("30");

    fireEvent.change(period, { target: { value: "7" } });
    await waitFor(() => expect(sinceDays(asked.at(-1))).toBe(7));
    fireEvent.change(period, { target: { value: "90" } });
    await waitFor(() => expect(sinceDays(asked.at(-1))).toBe(90));
    fireEvent.change(period, { target: { value: "all" } });
    await waitFor(() => expect(asked.at(-1)?.closed_since).toBeNull());
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual(
      expect.arrayContaining(["Last 7 days", "Last 30 days", "Last 90 days", "All"]),
    );
  });

  it("does not apply the period to the open operations: they are now", async () => {
    serve({ open: [opened(24 * 100, { markets: ["ANCIENTUSDT"] })], closed: [closed({ pair: "RECENTUSDT", hoursAgo: 3 })] });
    open();
    await loaded();

    fireEvent.change(screen.getByRole("combobox", { name: "Period" }), { target: { value: "7" } });

    expect(screen.getByRole("combobox", { name: "Period" })).toHaveValue("7");
    await waitFor(() => expect(rows().map((row) => textsOf(row)[COL.pair])).toEqual(["ANCIENTUSDT", "RECENTUSDT"]));
  });

  it("filters by strategy: the open ones here, the closed ones by the server, and the choices come from both", async () => {
    const asked = serve({
      open: [opened(1, { strategy_id: BETA, strategy_name: "Beta", markets: ["BETAOPEN"] }), opened(2, { markets: ["ALPHAOPEN"] })],
      closed: [closed({ strategy_id: BETA, strategy_name: "Beta", pair: "BETACLOSED" }), closed({ pair: "ALPHACLOSED" })],
      strategies: [{ id: ALPHA, name: "Alpha", archived: false }],
    });
    open();
    await loaded();

    const select = screen.getByRole("combobox", { name: "Strategy" });
    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "All strategies",
      "Alpha",
      "Beta",
    ]);
    fireEvent.change(select, { target: { value: BETA } });

    await waitFor(() => expect(asked.at(-1)?.strategy_id).toBe(BETA));
    await waitFor(() => expect(rows().map((row) => textsOf(row)[COL.pair])).toEqual(["BETAOPEN", "BETACLOSED"]));
  });

  it("filters by exchange the same way, the choices being the server's and the open positions'", async () => {
    const asked = serve({
      open: [opened(1, { markets: ["BYBITOPEN"] }), opened(2, { markets: ["BINOPEN"], pool: { exchange: "binance", venue: "usdt-m", settlement_currency: "USDT" } })],
      closed: [closed({ pair: "BYBITCLOSED" }), closed({ pair: "BINCLOSED", exchange: "binance" })],
      exchanges: ["bybit"],
    });
    open();
    await loaded();

    const select = screen.getByRole("combobox", { name: "Exchange" });
    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual(["All", "Binance", "Bybit"]);
    fireEvent.change(select, { target: { value: "binance" } });

    await waitFor(() => expect(asked.at(-1)?.exchange).toBe("binance"));
    await waitFor(() => expect(rows().map((row) => textsOf(row)[COL.pair])).toEqual(["BINOPEN", "BINCLOSED"]));
  });

  it("goes back to the first page when a filter changes", async () => {
    const asked = serve({ closed: Array.from({ length: 45 }, () => closed()), exchanges: ["bybit"] });
    open();
    await screen.findByText("Page 1 of 3");

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Page 2 of 3");
    fireEvent.change(screen.getByRole("combobox", { name: "Exchange" }), { target: { value: "bybit" } });

    await screen.findByText("Page 1 of 3");
    await waitFor(() => expect(asked.at(-1)).toMatchObject({ exchange: "bybit", offset: "0" }));
  });

  it("clears every filter, period included, with Clear filters", async () => {
    const asked = serve({
      open: [opened(1, { markets: ["OPENUSDT"] })],
      closed: [closed({ pair: "CLOSEDUSDT" })],
      strategies: [{ id: ALPHA, name: "Alpha", archived: false }],
      exchanges: ["bybit"],
    });
    open();
    await loaded();
    fireEvent.change(screen.getByRole("combobox", { name: "Period" }), { target: { value: "7" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Strategy" }), { target: { value: ALPHA } });
    fireEvent.change(screen.getByRole("combobox", { name: "Exchange" }), { target: { value: "bybit" } });
    await waitFor(() => expect(asked.at(-1)).toMatchObject({ strategy_id: ALPHA, exchange: "bybit" }));

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    await waitFor(() => expect(asked.at(-1)).toMatchObject({ strategy_id: null, exchange: null }));
    expect(screen.getByRole("combobox", { name: "Period" })).toHaveValue("30");
    expect(screen.getByRole("combobox", { name: "Strategy" })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Exchange" })).toHaveValue("");
  });
});

describe("My trades: amounts while the balances are hidden", () => {
  it("masks the entry, the exit and the PnL of open and closed rows, and leaves the dates and the pair", async () => {
    useHiddenStore.setState({ hidden: true });
    serve({ open: [opened(1)], closed: [closed()] });
    open();

    await loaded();
    for (const row of rows()) {
      const cells = cellsOf(row);
      expect(within(cells[COL.pnl] as HTMLElement).getByRole("img", { name: "Hidden" })).toBeInTheDocument();
      expect(cells[COL.pnl]).not.toHaveTextContent(/\d/);
      expect(cells[COL.pair]).toHaveTextContent("SOLUSDT");
    }
    const closedRow = rows()[1] as HTMLElement;
    expect(within(cellsOf(closedRow)[COL.entry] as HTMLElement).getByRole("img", { name: "Hidden" })).toBeInTheDocument();
    expect(within(cellsOf(closedRow)[COL.exit] as HTMLElement).getByRole("img", { name: "Hidden" })).toBeInTheDocument();
  });
});

describe("My trades: where the table does not fit", () => {
  it("turns each operation into a card on a phone, with the same facts and marks", async () => {
    setViewport("narrow");
    serve({ open: [opened(1, { markets: ["OPENUSDT"] })], closed: [closed({ pair: "CLOSEDUSDT", close_cause: "STOP_FIRED" })] });
    open();

    const cards = await screen.findAllByTestId("my-trade-row");
    expect(screen.queryByRole("table")).toBeNull();
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveTextContent("OPENUSDT");
    expect(cards[0]).toHaveTextContent("Open");
    expect(cards[1]).toHaveTextContent("CLOSEDUSDT");
    expect(cards[1]).toHaveTextContent("+5.50");
    expect(within(cards[1] as HTMLElement).getByTestId("my-trade-close-mark")).toHaveAccessibleName("The stop fired at the exchange");
    expect(screen.getByText("Page 1 of 1")).toBeInTheDocument();
  });
});

describe("My trades: loading, failure and an empty list", () => {
  it("says it is reading while the trades are on their way", async () => {
    stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) =>
      url.includes("/performance/trades") ? new Promise<Response>(() => undefined) : undefined,
    );
    open();

    expect(await screen.findByText("Reading trades…")).toHaveAttribute("role", "status");
  });

  it("says the read failed, and reads again on Try again", async () => {
    let failing = true;
    stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) => {
      if (!url.includes("/performance/trades")) return undefined;
      if (failing) return Promise.resolve(jsonResponse({ detail: "boom" }, 500));
      return Promise.resolve(jsonResponse({ trades: [closed()], total: 1, strategies: [], exchanges: [] }));
    });
    open();

    expect(await screen.findByRole("alert")).toHaveTextContent("Your trades could not be read.");
    failing = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    await loaded();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says nothing matches when the list is empty, and keeps the filters to change", async () => {
    serve({});
    open();

    expect(await screen.findByText("No trades match these filters.")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Period" })).toBeInTheDocument();
    expect(screen.getByTestId("my-trades-count")).toHaveTextContent("0 trades");
  });
});

describe("My trades: in Spanish, to usted", () => {
  it("writes the page, the filters, the marks and the pager in Spanish", async () => {
    await i18n.changeLanguage("es");
    serve({
      open: [opened(1)],
      closed: [closed({ close_cause: "STRATEGY_STOPPED_CLOSED" }), ...Array.from({ length: 25 }, () => closed())],
    });
    open();

    expect(await screen.findByRole("heading", { level: 1, name: "Mis operaciones" })).toBeInTheDocument();
    await loaded();
    expect(screen.getByText("Todas sus operaciones, de todas sus estrategias, en un solo lugar.")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Período" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Estrategia" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Limpiar filtros" })).toBeInTheDocument();
    expect(screen.getByTestId("my-trades-count")).toHaveTextContent("27 operaciones");
    expect(screen.getByText("Página 1 de 2")).toBeInTheDocument();
    expect(textsOf(rows()[0] as HTMLElement)[COL.closed]).toBe("Abierta");
    const mark = within(rows()[1] as HTMLElement).getByTestId("my-trade-close-mark");
    expect(mark).toHaveAccessibleName("Cierre de seguridad: la estrategia quedó desactivada con la operación abierta");
    expect(screen.getByRole("columnheader", { name: "Cierre (UTC)" })).toBeInTheDocument();
  });
});
