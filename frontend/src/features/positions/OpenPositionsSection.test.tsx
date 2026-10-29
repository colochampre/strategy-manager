import { useQueryClient } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OpenPositionsSection } from "@/features/positions/OpenPositionsSection";
import { StrategyDetailPage } from "@/features/strategies/StrategyDetailPage";
import { OPEN_POSITIONS_KEY } from "@/shared/api/positions";
import type { ConfirmedDiscrepancy } from "@/shared/api/discrepancies";
import type { OpenPosition } from "@/shared/api/positions";
import type { Strategy } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import {
  confirmedBody,
  discrepancy,
  failsOnceThenHolds,
  jsonResponse,
  lock,
  openOrder,
  openPosition,
  openState,
  renderAt,
  setViewport,
  strategyRoute,
  stubApi,
  unlock,
} from "@/test/harness";
import type { ConfirmedStub, OpenPositionsStub } from "@/test/harness";

/**
 * T10, the detail section: the table, its cells, its sub-rows, its notes, its states and its orders, and the
 * phone cards (design addendum § H, examples 13 to 21, 25d, 25e and 26b).
 */

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const ALPHA = "11111111-1111-4111-8111-111111111111";

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: ALPHA,
    name: "Alpha",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    subscription: null,
    enabled: true,
    archived_at: null,
    allowed_pairs: ["SOLUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    ...overrides,
  };
}

beforeEach(async () => {
  unlock();
  await act(() => i18n.changeLanguage("en"));
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

/** Lets the stubbed answers reach the components. */
async function settle() {
  for (let turn = 0; turn < 3; turn += 1) await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
}

const answering = (...args: Parameters<typeof openState>): OpenPositionsStub => ({ kind: "ok", body: openState(...args) });

async function mountSection(openPositions: OpenPositionsStub, subject = strategy(), bookings: unknown[] = []) {
  const api = stubApi(HEALTH, bookings, undefined, {}, undefined, {}, undefined, openPositions);
  const view = renderAt(<OpenPositionsSection strategy={subject} />);
  await settle();
  return { api, view };
}

/** The table, asserted to exist before it is returned, so that its absence is a failed assertion. */
function theTable(): HTMLElement {
  expect(screen.queryByRole("table")).toBeInTheDocument();
  return screen.getByRole("table");
}

/** The rows of the table that are positions (eight cells), not sub-rows (one cell across the eight). */
function positionRows(table: HTMLElement): HTMLElement[] {
  return within(table)
    .getAllByRole("row")
    .filter((row) => row.querySelectorAll("td").length === 8);
}

function cellsOf(row: HTMLElement): HTMLElement[] {
  return [...row.querySelectorAll<HTMLElement>("td")];
}

const COLUMN = { opened: 0, pair: 1, side: 2, size: 3, entry: 4, fees: 5, margin: 6, leverage: 7 } as const;

/** The one position row of a table that holds one, and its cells. */
function onlyRow(): HTMLElement[] {
  const rows = positionRows(theTable());
  expect(rows).toHaveLength(1);
  return cellsOf(rows[0] as HTMLElement);
}

/** A position the facts could not decorate: every nullable field is null (design § F). */
function noFacts(overrides: Partial<OpenPosition> = {}): OpenPosition {
  return openPosition({
    strategy_id: ALPHA,
    markets: ["STXUSDT"],
    origin: "live",
    figures_missing: "NO_FACTS",
    side: null,
    base_currency: null,
    size: null,
    opened_size: null,
    entry_price: null,
    opened_at: null,
    fill_count: 0,
    fees: null,
    margin_granted: null,
    leverage: null,
    reservation_status: null,
    ...overrides,
  });
}

/** The spec's live AAVEUSDT LONG of 0.82 at 184.3, fees 0.17, margin 121.80 and leverage 2.00000000. */
function aave(overrides: Partial<OpenPosition> = {}): OpenPosition {
  return openPosition({
    strategy_id: ALPHA,
    markets: ["AAVEUSDT"],
    base_currency: "AAVE",
    side: "LONG",
    origin: "live",
    size: "0.82000000",
    opened_size: "0.82000000",
    entry_price: "184.300000000000000000",
    opened_at: "2026-10-11T14:05:11Z",
    fill_count: 1,
    fees: "0.17000000",
    other_fees: [],
    margin_granted: "121.8",
    leverage: "2.00000000",
    ...overrides,
  });
}

describe("the cells of a position (T10; spec 'Times And Figures Of Open Positions Are Written One Way')", () => {
  it("lists a live position with every column, the heading of the margin naming the currency", async () => {
    await mountSection(answering([aave()]));

    const table = theTable();
    const headings = within(table)
      .getAllByRole("columnheader")
      .map((heading) => heading.textContent);
    expect(headings).toEqual([
      "Opened (UTC)",
      "Pair",
      "Side",
      "Size",
      "Entry",
      "Fees USDT",
      "Margin granted USDT",
      "Leverage",
    ]);

    const cells = onlyRow();
    const date = cells[COLUMN.opened]?.querySelectorAll(".block");
    expect([...(date ?? [])].map((part) => part.textContent)).toEqual(["10/11/2026", "14:05"]);
    expect(date?.[1]).toHaveClass("text-ink-3");
    expect(cells[COLUMN.pair]?.textContent).toBe("AAVEUSDTLive");
    expect(cells[COLUMN.side]?.textContent).toBe("LONG");
    expect(cells[COLUMN.size]?.textContent).toBe("0.82 AAVE");
    expect(cells[COLUMN.entry]?.textContent).toBe("184.3");
    expect(cells[COLUMN.fees]?.textContent).toBe("0.17");
    expect(cells[COLUMN.margin]?.textContent).toBe("121.80");
    expect(cells[COLUMN.leverage]?.textContent).toBe("2x");
  });

  it("writes the origin's word under the pair, in the sans type, in the origin's token", async () => {
    await mountSection(
      answering([aave({ origin: "rehearsal" }), aave({ origin: "live", markets: ["LINKUSDT"] }), aave({ origin: "mixed", markets: ["STXUSDT"] })]),
    );

    const rows = positionRows(theTable());
    const words = rows.map((row) => {
      const word = cellsOf(row)[COLUMN.pair]?.querySelector(".block") as HTMLElement;
      return [word.textContent, word.className, word.firstElementChild?.className];
    });
    expect(words).toEqual([
      ["Dry run", expect.stringContaining("font-sans"), expect.stringContaining("text-decision")],
      ["Live", expect.stringContaining("font-sans"), expect.stringContaining("text-gain")],
      ["Dry run and live", expect.stringContaining("font-sans"), expect.stringContaining("text-loss")],
    ]);
    for (const row of rows) expect(cellsOf(row)[COLUMN.pair]?.querySelector(".block")).toHaveClass("text-[11px]");
  });

  it("writes the base currency as a unit, in the sans type and the faint ink", async () => {
    await mountSection(answering([aave()]));

    const unit = onlyRow()[COLUMN.size]?.querySelector(".font-sans") as HTMLElement;
    expect(unit).toHaveTextContent("AAVE");
    expect(unit).toHaveClass("text-[11px]", "text-ink-3");
  });

  it("says what was opened under the size, only when it differs from the size", async () => {
    await mountSection(
      answering([aave({ size: "0.3", opened_size: "0.5" }), aave({ markets: ["LINKUSDT"], size: "0.5", opened_size: "0.50000000" })]),
    );

    const [partial, whole] = positionRows(theTable()).map(cellsOf) as [HTMLElement[], HTMLElement[]];
    expect(partial[COLUMN.size]).toHaveTextContent("0.3 AAVE");
    expect(within(partial[COLUMN.size] as HTMLElement).getByText("of 0.5 opened")).toHaveClass("block", "font-sans", "text-[11px]", "text-ink-3");
    expect(whole[COLUMN.size]?.textContent).not.toContain("opened");
  });

  it("says that the entry is an average only above one fill", async () => {
    await mountSection(answering([aave({ fill_count: 3 }), aave({ markets: ["LINKUSDT"], fill_count: 1 })]));

    const [three, one] = positionRows(theTable()).map(cellsOf) as [HTMLElement[], HTMLElement[]];
    expect(three[COLUMN.entry]).toHaveTextContent("184.3");
    expect(within(three[COLUMN.entry] as HTMLElement).getByText("average of 3 fills")).toBeInTheDocument();
    expect(one[COLUMN.entry]?.textContent).toBe("184.3");
  });

  it("writes a fee in another currency beside the fees, as the closed trades table does", async () => {
    await mountSection(answering([aave({ other_fees: [{ currency: "SOL", amount: "0.00100000" }] })]));

    const fees = onlyRow()[COLUMN.fees] as HTMLElement;
    expect(fees.textContent).toBe("0.17+ 0.001 SOL");
    expect(within(fees).getByText("+ 0.001 SOL")).toHaveClass("ml-2", "font-sans", "text-[11px]", "text-ink-3");
  });

  it("writes the margin with the currency's decimals: two for USDT, eight for BTC", async () => {
    await mountSection(
      answering([
        aave({ margin_granted: "121.8" }),
        aave({ markets: ["BTCUSD"], currency: "BTC", margin_granted: "0.0012345678", fees: "0.0000123" }),
      ]),
    );

    const [usdt, btc] = positionRows(theTable()).map(cellsOf) as [HTMLElement[], HTMLElement[]];
    expect(usdt[COLUMN.margin]?.textContent).toBe("121.80");
    expect(btc[COLUMN.margin]?.textContent).toBe("0.00123457");
    expect(btc[COLUMN.fees]?.textContent).toBe("0.00001230");
  });

  it.each([
    ["2.00000000", "2x"],
    ["1.00000000", "1x"],
    ["2.50000000", "2.5x"],
    ["10.00000000", "10x"],
  ])("writes the served leverage %s as %s, never the served string", async (served, written) => {
    await mountSection(answering([aave({ leverage: served })]));

    expect(onlyRow()[COLUMN.leverage]?.textContent).toBe(written);
  });

  it("reads 1x for a rehearsal position, because 1 was recorded", async () => {
    await mountSection(answering([aave({ origin: "rehearsal", leverage: "1.00000000" })]));

    expect(onlyRow()[COLUMN.leverage]?.textContent).toBe("1x");
  });

  it("draws no notional, no unrealised PnL and no current price anywhere in the section", async () => {
    const { view } = await mountSection(answering([aave()]));

    const text = (view.container.textContent ?? "").toLowerCase();
    for (const word of ["notional", "unrealised", "unrealized", "pnl", "current price", "mark price"]) expect(text).not.toContain(word);
    expect(within(theTable()).getAllByRole("columnheader")).toHaveLength(8);
  });

  it("selects the strategy's positions over the WHOLE answer, wherever the ledger put them", async () => {
    const elsewhere = aave({ markets: ["ELSEUSDT"], pool: { exchange: "binance", venue: "usdt-m", settlement_currency: "USDT" } });
    const another = aave({ markets: ["OTHERUSDT"], strategy_id: "22222222-2222-4222-8222-222222222222" });
    const nobody = aave({ markets: ["NOBODYUSDT"], strategy_id: null, figures_missing: "NO_FACTS" });
    await mountSection(answering([aave({ markets: ["HEREUSDT"] }), elsewhere, another, nobody]));

    const pairs = positionRows(theTable()).map((row) => cellsOf(row)[COLUMN.pair]?.textContent);
    expect(pairs).toEqual(["HEREUSDTLive", "ELSEUSDTLive"]);
  });

  it("lists dry-run and live positions together, each with its origin's word", async () => {
    await mountSection(answering([aave({ origin: "rehearsal", markets: ["SFPUSDT"] }), aave({ origin: "live", markets: ["AAVEUSDT"] })]));

    const pairs = positionRows(theTable()).map((row) => cellsOf(row)[COLUMN.pair]?.textContent);
    expect(pairs).toEqual(["SFPUSDTDry run", "AAVEUSDTLive"]);
  });
});

const ALLOCATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const DISCREPANCY = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";

/** The discrepancy the position's disagreement names; its symbol is the TradingView spelling, the position's is the venue's (R21). */
function confirmedItem(overrides: Partial<ConfirmedDiscrepancy> = {}): ConfirmedDiscrepancy {
  return discrepancy({ discrepancy_id: DISCREPANCY, symbol: "AAVEUSDT.P", ...overrides });
}

const BEING_BOOKED: ConfirmedStub = {
  kind: "ok",
  body: confirmedBody({ being_booked: [confirmedItem({ reason: null })] }),
};
const NEEDS_OWNER: ConfirmedStub = {
  kind: "ok",
  body: confirmedBody({ needs_owner: [confirmedItem({ reason: "NOT_BOOKED" })] }),
};

/** AAVEUSDT, which the venue disagrees on: it holds 0.82 in the ledger and 0 at the exchange. */
function disagreeing(overrides: Partial<OpenPosition> = {}): OpenPosition {
  return aave({
    allocation_id: ALLOCATION,
    venue_disagreement: {
      discrepancy_id: DISCREPANCY,
      venue_net_base: "0",
      ledger_net_base: "0.82000000",
      allocation_count: 1,
      last_observed_at: "2026-10-12T21:39:12Z",
    },
    ...overrides,
  });
}

/** Mounts the section over one positions answer and one answer to the confirmed discrepancies. */
async function mountWithConfirmed(position: OpenPosition, confirmed: ConfirmedStub, asOf = "2026-10-12T21:40:03Z") {
  stubApi(HEALTH, [], undefined, {}, undefined, {}, undefined, answering([position], [], asOf), confirmed);
  const view = renderAt(<OpenPositionsSection strategy={strategy()} />);
  await settle();
  return view;
}

/** What follows a position's row: every row up to the next position's, as its cells. */
function subRowsOf(table: HTMLElement, index = 0): HTMLElement[] {
  const rows = within(table).getAllByRole("row");
  const own = positionRows(table)[index] as HTMLElement;
  const after = rows.slice(rows.indexOf(own) + 1);
  const next = after.findIndex((row) => row.querySelectorAll("td").length === 8);
  return next === -1 ? after : after.slice(0, next);
}

/** The first sub-row of the first position, asserted to exist before it is returned. */
function firstSubRow(table: HTMLElement, index = 0): HTMLElement {
  const subs = subRowsOf(table, index);
  expect(subs.length).toBeGreaterThan(0);
  return subs[0] as HTMLElement;
}

const LINK = "See the discrepancy";
const WORDS = "being booked automatically";

describe("the sub-rows (T10, T19 and T18, the line's half)", () => {
  it("is a real row of one cell across the eight columns, directly under its position's row", async () => {
    await mountSection(answering([aave({ figures_missing: "UNRESOLVED_SYMBOL", side: null, size: null, entry_price: null })]));

    const table = theTable();
    const rows = within(table).getAllByRole("row");
    const own = positionRows(table)[0] as HTMLElement;
    const sub = rows[rows.indexOf(own) + 1] as HTMLElement;
    expect(sub).toBeDefined();
    expect(sub.tagName).toBe("TR");
    expect(sub.parentElement).toBe(own.parentElement);
    expect(sub.querySelectorAll("td")).toHaveLength(1);
    expect((sub.querySelector("td") as HTMLTableCellElement).colSpan).toBe(8);
    expect(sub.className).not.toMatch(/\bflex\b/);
  });

  it("gives the reason the figures are missing, in the sans type, small, in the secondary ink", async () => {
    await mountSection(answering([aave({ figures_missing: "UNRESOLVED_SYMBOL", side: null, size: null, entry_price: null })]));

    const sub = firstSubRow(theTable());
    expect(sub).toHaveTextContent(
      "The pair's base currency cannot be told from the pool's currency, so the side and the size are not derived.",
    );
    const reason = within(sub as HTMLElement).getByText(/base currency cannot be told/);
    expect(reason).toHaveClass("font-sans", "text-xs", "text-ink-2");
  });

  it.each([
    ["SEVERAL_MARKETS", "The fills of this position name more than one pair."],
    ["FLIPPED", "The fills sold more than was bought, or bought more than was sold. The entry price is not derived."],
    ["INCONSISTENT", "The figures could not be derived from the fills."],
    ["NO_FACTS", "The figures could not be derived from the fills."],
    ["SOMETHING_NEW", "The figures could not be derived from the fills."],
  ])("gives %s its own text, and any other reason the generic one", async (code, text) => {
    await mountSection(answering([aave({ figures_missing: code })]));

    const subs = subRowsOf(theTable());
    expect(subs).toHaveLength(1);
    expect(subs[0]).toHaveTextContent(text);
  });

  it("draws no sub-row for a position whose figures are all there", async () => {
    await mountSection(answering([aave()]));

    expect(subRowsOf(theTable())).toEqual([]);
  });

  it("draws the reservation's note when its status is not FILLED, and none when it is FILLED", async () => {
    await mountSection(
      answering([aave({ reservation_status: "EXPIRED" }), aave({ markets: ["LINKUSDT"], reservation_status: "FILLED" })]),
    );

    const table = theTable();
    const first = firstSubRow(table, 0);
    expect(first).toHaveTextContent("Its reservation reads EXPIRED, not FILLED.");
    expect(subRowsOf(table, 1)).toEqual([]);
  });

  it("puts the venue line first, then the reason, then the reservation's note", async () => {
    await mountWithConfirmed(
      disagreeing({ figures_missing: "UNRESOLVED_SYMBOL", side: null, size: null, entry_price: null, reservation_status: "EXPIRED" }),
      BEING_BOOKED,
    );

    const subs = subRowsOf(theTable());
    expect(subs).toHaveLength(3);
    expect(within(subs[0] as HTMLElement).getByRole("group", { name: "Venue disagrees, AAVEUSDT" })).toBeInTheDocument();
    expect(subs[1]).toHaveTextContent("The pair's base currency cannot be told");
    expect(subs[2]).toHaveTextContent("Its reservation reads EXPIRED, not FILLED.");
    for (const sub of subs) expect((sub.querySelector("td") as HTMLTableCellElement).colSpan).toBe(8);
  });

  it("draws the venue line, solid red, across the table's width under its row", async () => {
    await mountWithConfirmed(disagreeing(), BEING_BOOKED);

    const sub = firstSubRow(theTable());
    const line = within(sub as HTMLElement).getByRole("group", { name: "Venue disagrees, AAVEUSDT" });
    expect(line).toHaveClass("border-loss", "w-full");
    expect(line).not.toHaveClass("border-dashed");
    expect(line.textContent).toBe(
      "AAVEUSDT · venue disagrees · exchange 0 AAVE, ledger 0.82 AAVE · last compared 21:39:12 UTC · being booked automatically · See the discrepancy",
    );
  });

  it("draws the link to the item on the discrepancies page when the id is in being_booked", async () => {
    await mountWithConfirmed(disagreeing(), BEING_BOOKED);

    const link = await screen.findByRole("link", { name: `${LINK}, AAVEUSDT` });
    expect(link).toHaveAttribute("href", `/discrepancies#discrepancy-${DISCREPANCY}`);
    expect(firstSubRow(theTable())).toHaveTextContent(WORDS);
  });

  it("says the words of the reason, and keeps the line red, when the id is in needs_owner", async () => {
    await mountWithConfirmed(disagreeing(), NEEDS_OWNER);

    const link = await screen.findByRole("link", { name: `${LINK}, AAVEUSDT` });
    expect(link).toHaveAttribute("href", `/discrepancies#discrepancy-${DISCREPANCY}`);
    const sub = firstSubRow(theTable());
    expect(sub).toHaveTextContent("could not be booked automatically");
    expect(sub).not.toHaveTextContent(WORDS);
    expect(within(sub as HTMLElement).getByRole("group", { name: "Venue disagrees, AAVEUSDT" })).toHaveClass("border-loss");
  });

  it.each([
    ["the discrepancies are loading", { kind: "pending" } as ConfirmedStub],
    ["their read failed", { kind: "status", status: 500, body: { detail: "down" } } as ConfirmedStub],
    ["the id is in neither list", { kind: "ok", body: confirmedBody() } as ConfirmedStub],
  ])("draws neither the link nor the words while %s", async (_label, answer) => {
    await mountWithConfirmed(disagreeing(), answer);

    const sub = firstSubRow(theTable());
    expect(sub.textContent).toBe(
      "AAVEUSDT · venue disagrees · exchange 0 AAVE, ledger 0.82 AAVE · last compared 21:39:12 UTC",
    );
    expect(within(sub as HTMLElement).queryByRole("link")).not.toBeInTheDocument();
  });

  it("writes 'last compared' with its date when the instant is of the day before the answer's", async () => {
    await mountWithConfirmed(
      disagreeing({
        venue_disagreement: {
          discrepancy_id: DISCREPANCY,
          venue_net_base: "0",
          ledger_net_base: "0.82",
          allocation_count: 1,
          last_observed_at: "2026-10-11T21:12:00Z",
        },
      }),
      BEING_BOOKED,
    );

    const sub = firstSubRow(theTable());
    expect(sub).toHaveTextContent("last compared 10/11/2026 21:12:00 UTC");
  });
});

const NOTE = {
  rehearsal: "A dry-run position was filled by the simulated exchange, at 1x. It is not at the exchange and enters no total.",
  mixed: "This position holds dry-run and live fills. Neither mode can close it safely: check it against the exchange by hand.",
  margin: "Margin granted is what the share took from the pool when the position opened. It is not what the exchange holds now.",
} as const;

/** The notes on screen, in document order, as their keys. */
function notesOnScreen(container: HTMLElement): string[] {
  const names = Object.entries(NOTE);
  return [...container.querySelectorAll("p")].flatMap((paragraph) => {
    const found = names.find(([, text]) => paragraph.textContent === text);
    return found === undefined ? [] : [found[0]];
  });
}

/** An element no strategy owns, on the strategy's own exchange. */
function unowned(overrides: Partial<OpenPosition> = {}): OpenPosition {
  return noFacts({ strategy_id: null, strategy_archived: null, strategy_name: "Nobody", markets: ["XYZBTC"], ...overrides });
}

const MATCHED_ONE = "1 open position or order could not be matched to a strategy. The Strategies page names it.";
const MATCHED_TWO = "2 open positions or orders could not be matched to a strategy. The Strategies page names them.";
const MATCHED_ONE_ES = "1 posición u orden abierta no se pudo asociar a una estrategia. La página Estrategias la nombra.";

describe("the notes and the unmatched sentence (T10; spec 'Drawn Only When True')", () => {
  it("draws only the margin note for one live position", async () => {
    const { view } = await mountSection(answering([aave()]));

    expect(notesOnScreen(view.container)).toEqual(["margin"]);
  });

  it("draws the dry-run note, then the margin note, for a rehearsal position", async () => {
    const { view } = await mountSection(answering([aave({ origin: "rehearsal" })]));

    expect(notesOnScreen(view.container)).toEqual(["rehearsal", "margin"]);
  });

  it("draws the note of both origins, not the dry-run note, then the margin note, for a mixed position", async () => {
    const { view } = await mountSection(answering([aave({ origin: "mixed" })]));

    expect(notesOnScreen(view.container)).toEqual(["mixed", "margin"]);
  });

  it("orders the notes dry-run, both origins, margin", async () => {
    const { view } = await mountSection(
      answering([aave({ origin: "mixed", markets: ["STXUSDT"] }), aave({ origin: "rehearsal", markets: ["SFPUSDT"] })]),
    );

    expect(notesOnScreen(view.container)).toEqual(["rehearsal", "mixed", "margin"]);
  });

  it("draws the margin note once, whatever the number of positions", async () => {
    const { view } = await mountSection(answering([aave(), aave({ markets: ["LINKUSDT"] }), aave({ markets: ["SUIUSDT"] })]));

    expect(notesOnScreen(view.container)).toEqual(["margin"]);
  });

  it("draws no note when the strategy holds no position", async () => {
    const { view } = await mountSection(answering([]));

    expect(notesOnScreen(view.container)).toEqual([]);
    expect(screen.queryByText("No open position.")).toBeInTheDocument();
  });

  it("says that one element could not be matched, in place of 'No open position.', when the strategy holds none", async () => {
    await mountSection(answering([unowned()]));

    expect(screen.queryByText(MATCHED_ONE)).toBeInTheDocument();
    expect(screen.queryByText("No open position.")).not.toBeInTheDocument();
  });

  it("says 'position or order' for one in-flight order that no strategy owns and no position at all", async () => {
    await mountSection(answering([], [{ ...openOrder(), strategy_id: null, strategy_name: null }]));

    expect(screen.queryByText(MATCHED_ONE)).toBeInTheDocument();
    expect(screen.queryByText("No open position.")).not.toBeInTheDocument();
  });

  it("counts positions and orders together, in the plural", async () => {
    await mountSection(answering([unowned()], [{ ...openOrder(), strategy_id: null, strategy_name: null }]));

    expect(screen.queryByText(MATCHED_TWO)).toBeInTheDocument();
    expect(screen.queryByText("No open position.")).not.toBeInTheDocument();
  });

  it("says it above the notes, under the table, when the strategy holds a position of its own", async () => {
    const { view } = await mountSection(answering([aave(), unowned(), unowned({ markets: ["ABCBTC"] })]));

    expect(screen.queryByText(MATCHED_TWO)).toBeInTheDocument();
    const sentence = screen.getByText(MATCHED_TWO);
    const table = theTable();
    const margin = screen.getByText(NOTE.margin);
    expect(table.compareDocumentPosition(sentence) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(sentence.compareDocumentPosition(margin) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(view.container.textContent).not.toContain("No open position.");
  });

  it("does not count an unmatched element of ANOTHER exchange, and still says 'No open position.'", async () => {
    await mountSection(
      answering([unowned({ pool: { exchange: "binance", venue: "usdt-m", settlement_currency: "USDT" } })]),
    );

    expect(screen.queryByText("No open position.")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("could not be matched");
  });
});

/** Every English text of the section (section I), which a Spanish render must not contain. */
const ENGLISH_OF_THE_SECTION = [
  "Open positions",
  "No open position",
  "Reading open positions",
  "Opened (UTC)",
  "Margin granted",
  "Leverage",
  "not recorded",
  "figures not readable",
  "of 0.5 opened",
  "average of",
  "order in flight",
  "opening",
  "closing",
  "sent ",
  "Dry run",
  "Live",
  "venue disagrees",
  "last compared",
  "shared by",
  "being booked automatically",
  "See the discrepancy",
  "A dry-run position was filled",
  "This position holds dry-run",
  "Margin granted is what the share took",
  "Its reservation reads",
  "The pair's base currency cannot be told",
  "could not be matched to a strategy",
  "Fees ",
];

describe("in Spanish (T10 and T11; owner decision Q9, 2026-10-13)", () => {
  async function spanishSection() {
    await act(() => i18n.changeLanguage("es"));
    const wholeRow = disagreeing({
      markets: ["AAVEUSDT"],
      size: "0.3",
      opened_size: "0.5",
      fill_count: 3,
      figures_missing: "UNRESOLVED_SYMBOL",
      reservation_status: "EXPIRED",
      venue_disagreement: {
        discrepancy_id: DISCREPANCY,
        venue_net_base: "0",
        ledger_net_base: "0.82",
        allocation_count: 2,
        last_observed_at: "2026-10-12T21:39:12Z",
      },
    });
    stubApi(
      HEALTH,
      [],
      undefined,
      {},
      undefined,
      {},
      undefined,
      answering(
        [wholeRow, aave({ origin: "rehearsal", markets: ["SFPUSDT"], leverage: null }), aave({ origin: "mixed", markets: ["STXUSDT"] }), unowned()],
        [openOrder({ strategy_id: ALPHA, action: "CLOSE", origin: "rehearsal" })],
      ),
      BEING_BOOKED,
    );
    const view = renderAt(<OpenPositionsSection strategy={strategy()} />);
    await settle();
    await screen.findByRole("link", { name: "Ver la discrepancia, AAVEUSDT" });
    return view;
  }

  it("finds none of section I's English anywhere in the section", async () => {
    const view = await spanishSection();

    const text = view.container.textContent ?? "";
    for (const english of ENGLISH_OF_THE_SECTION) expect(text, english).not.toContain(english);
  });

  it("writes the fixed Spanish of section I, letter for letter", async () => {
    const view = await spanishSection();

    const text = view.container.textContent ?? "";
    for (const spanish of [
      "Posiciones abiertas",
      "Apertura (UTC)",
      "Margen otorgado USDT",
      "Apalancamiento",
      "Comisiones USDT",
      "de 0.5 abiertas",
      "promedio de 3 ejecuciones",
      "no registrado",
      "orden en curso · cierre · Simulación · enviada 21:12 UTC",
      "el exchange no coincide",
      "exchange 0 AAVE, libro mayor 0.82 AAVE",
      "última comparación 21:39:12 UTC",
      "compartida por 2 posiciones en este par",
      "se está registrando automáticamente",
      "Ver la discrepancia",
      "La moneda base del par no se puede determinar a partir de la moneda del pool, por lo que el lado y el tamaño no se calculan.",
      "Su reserva figura como EXPIRED, no FILLED.",
      "Una posición de simulación fue ejecutada por el exchange simulado, a 1x. No está en el exchange real y no entra en ningún total.",
      "Esta posición tiene ejecuciones de simulación y en vivo. Ningún modo puede cerrarla con seguridad: verifíquela a mano contra el exchange.",
      "El margen otorgado es lo que la participación tomó del pool al abrir la posición. No es lo que el exchange retiene ahora.",
      MATCHED_ONE_ES,
    ]) {
      expect(text, spanish).toContain(spanish);
    }
  });

  it("reads the plural sentence of the unmatched in Spanish, in agreement", async () => {
    await act(() => i18n.changeLanguage("es"));
    await mountSection(answering([unowned(), unowned({ markets: ["ABCBTC"] })]));

    expect(screen.queryByText("2 posiciones u órdenes abiertas no se pudieron asociar a una estrategia. La página Estrategias las nombra.")).toBeInTheDocument();
  });

  it("reads the sentence for one unmatched order and no position in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    await mountSection(answering([], [{ ...openOrder(), strategy_id: null, strategy_name: null }]));

    expect(screen.queryByText(MATCHED_ONE_ES)).toBeInTheDocument();
  });

  it("reads 'Sin posiciones abiertas.' for an empty section", async () => {
    await act(() => i18n.changeLanguage("es"));
    await mountSection(answering([]));

    expect(screen.queryByText("Sin posiciones abiertas.")).toBeInTheDocument();
  });

  it("writes a price and a size with a POINT, as the closed trades table does, and money with the language's separator", async () => {
    await act(() => i18n.changeLanguage("es"));
    await mountSection(answering([aave()]));

    const cells = onlyRow();
    expect(cells[COLUMN.size]?.textContent).toBe("0.82 AAVE");
    expect(cells[COLUMN.entry]?.textContent).toBe("184.3");
    expect(cells[COLUMN.fees]?.textContent).toBe("0,17");
    expect(cells[COLUMN.margin]?.textContent).toBe("121,80");
    expect(cells[COLUMN.leverage]?.textContent).toBe("2x");
    expect(cells[COLUMN.opened]?.textContent).toBe("11/10/202614:05");
  });

  it("writes the same figures in a card", async () => {
    await act(() => i18n.changeLanguage("es"));
    setViewport("narrow");
    await mountSection(answering([aave()]));

    expect(valuesOf(cards(1)[0] as HTMLElement)).toEqual({
      "Apertura (UTC)": "11/10/2026 14:05",
      Tamaño: "0.82 AAVE",
      Entrada: "184.3",
      "Comisiones USDT": "0,17",
      "Margen otorgado USDT": "121,80",
      Apalancamiento: "2x",
    });
  });
});

const MD = "(min-width: 768px)";

/** The cards on screen, asserted to exist before they are returned. */
function cards(count: number): HTMLElement[] {
  const found = screen.queryAllByRole("article");
  expect(found).toHaveLength(count);
  return found;
}

/** The labelled values of a card, as label to value. */
function valuesOf(card: HTMLElement): Record<string, string> {
  return Object.fromEntries(
    [...card.querySelectorAll("dl > div")].map((pair) => [pair.querySelector("dt")?.textContent ?? "", pair.querySelector("dd")?.textContent ?? ""]),
  );
}

describe("on a phone the positions are cards (T10; N2: the prototype's example 20 decides)", () => {
  const THREE = [
    aave(),
    aave({ markets: ["LINKUSDT"], base_currency: "LINK", side: "SHORT", size: "12", opened_size: "12", entry_price: "17.43", fees: "0.21", margin_granted: "69.72", leverage: "3.00000000", opened_at: "2026-10-09T04:00:00Z" }),
    aave({ markets: ["SUIUSDT"], base_currency: "SUI", origin: "rehearsal", size: "140", opened_size: "140", entry_price: "3.2415", fees: "0.25", margin_granted: "226.9", leverage: "1.00000000", opened_at: "2026-10-10T12:00:00Z" }),
  ];

  it("renders a table at desktop width and no card", async () => {
    setViewport("wide");
    await mountSection(answering(THREE));

    expect(positionRows(theTable())).toHaveLength(3);
    expect(screen.queryAllByRole("article")).toHaveLength(0);
  });

  it("renders one article per position below md and no table", async () => {
    setViewport("narrow");
    await mountSection(answering(THREE));

    cards(3);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("chooses between the two at md (768 px), not at lg", async () => {
    const asked: string[] = [];
    vi.stubGlobal("matchMedia", (query: string) => {
      asked.push(query);
      return { matches: true, media: query, addEventListener: () => undefined, removeEventListener: () => undefined };
    });
    await mountSection(answering(THREE));

    expect(asked).toContain(MD);
    expect(screen.queryByRole("table")).toBeInTheDocument();
  });

  it("names each card by its pair and side, composed in the component", async () => {
    setViewport("narrow");
    await mountSection(answering(THREE));

    expect(cards(3).map((card) => card.getAttribute("aria-label"))).toEqual(["AAVEUSDT LONG", "LINKUSDT SHORT", "SUIUSDT LONG"]);
    expect(screen.queryByRole("article", { name: "AAVEUSDT LONG" })).toBeInTheDocument();
  });

  it("puts the pair and the side in the head, with the origin's word at its right", async () => {
    setViewport("narrow");
    await mountSection(answering(THREE));

    const [live, , dry] = cards(3) as [HTMLElement, HTMLElement, HTMLElement];
    const head = live.firstElementChild as HTMLElement;
    expect([...head.children].map((part) => part.textContent)).toEqual(["AAVEUSDTLONG", "Live"]);
    expect(head.lastElementChild).toHaveClass("text-gain");
    expect((dry.firstElementChild as HTMLElement).lastElementChild).toHaveTextContent("Dry run");
  });

  it("carries the same six labels and values in two columns", async () => {
    setViewport("narrow");
    await mountSection(answering(THREE));

    const [aaveCard, linkCard] = cards(3) as [HTMLElement, HTMLElement, HTMLElement];
    expect(valuesOf(aaveCard)).toEqual({
      "Opened (UTC)": "10/11/2026 14:05",
      Size: "0.82 AAVE",
      Entry: "184.3",
      "Fees USDT": "0.17",
      "Margin granted USDT": "121.80",
      Leverage: "2x",
    });
    expect(valuesOf(linkCard)).toMatchObject({ Size: "12 LINK", Entry: "17.43", "Margin granted USDT": "69.72", Leverage: "3x" });
    expect(aaveCard.querySelector("dl")).toHaveClass("grid", "grid-cols-2");
  });

  it("writes each null as a dash with its reason, in the card as in the table", async () => {
    setViewport("narrow");
    await mountSection(answering([noFacts({ strategy_id: ALPHA })]));

    const [card] = cards(1) as [HTMLElement];
    expect(card.getAttribute("aria-label")).toBe("STXUSDT side not readable");
    const values = valuesOf(card);
    for (const label of ["Opened (UTC)", "Size", "Entry", "Fees USDT", "Margin granted USDT", "Leverage"]) {
      expect(values[label], label).toBe("—figures not readable");
    }
  });

  it("names the leverage of a position that has its facts and none recorded 'not recorded'", async () => {
    setViewport("narrow");
    await mountSection(answering([aave({ leverage: null })]));

    expect(valuesOf(cards(1)[0] as HTMLElement).Leverage).toBe("—not recorded");
  });

  it("makes the sub-rows the card's last elements, in the order of the table's: venue line, reason, reservation", async () => {
    setViewport("narrow");
    await mountWithConfirmed(
      disagreeing({ figures_missing: "UNRESOLVED_SYMBOL", side: null, size: null, entry_price: null, reservation_status: "EXPIRED" }),
      BEING_BOOKED,
    );

    const [card] = cards(1) as [HTMLElement];
    const parts = [...card.children];
    expect(parts).toHaveLength(5);
    expect(parts[0]).toHaveTextContent("AAVEUSDT");
    expect(parts[1]?.tagName).toBe("DL");
    expect(within(parts[2] as HTMLElement).getByRole("group", { name: "Venue disagrees, AAVEUSDT" })).toBeInTheDocument();
    expect(parts[3]).toHaveTextContent("The pair's base currency cannot be told");
    expect(parts[4]).toHaveTextContent("Its reservation reads EXPIRED, not FILLED.");
  });

  it("draws the orders, the unmatched sentence and the notes under the cards", async () => {
    setViewport("narrow");
    await mountSection(answering([aave({ origin: "rehearsal" }), unowned()], [openOrder({ strategy_id: ALPHA })]));

    const card = (cards(1)[0] as HTMLElement).textContent ?? "";
    const page = document.body.textContent ?? "";
    const afterCard = page.indexOf(card) + card.length;
    for (const text of ["SOLUSDT · order in flight", MATCHED_ONE, NOTE.rehearsal, NOTE.margin]) {
      expect(page.indexOf(text), text).toBeGreaterThanOrEqual(afterCard);
    }
  });
});

describe("its place on the detail page (T10)", () => {
  it("is a full-width block between the two-column grid and the closed trades", async () => {
    stubApi(HEALTH, [], undefined, {}, strategyRoute(ALPHA, "Alpha"), {}, undefined, answering([aave()]));
    renderAt(
      <Routes>
        <Route path="strategies/:strategyId" element={<StrategyDetailPage />} />
      </Routes>,
      `/strategies/${ALPHA}`,
    );

    const open = await screen.findByRole("heading", { level: 2, name: "Open positions" });
    const closed = await screen.findByRole("heading", { level: 2, name: "Closed trades" });
    const settings = await screen.findByRole("complementary");
    expect(settings.compareDocumentPosition(open) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(open.compareDocumentPosition(closed) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const section = open.closest("section") as HTMLElement;
    // The framed section wraps it, and that wrapper is the full-width block.
    const framed = section.closest('[data-testid="report-section"]') as HTMLElement;
    expect(framed).not.toBeNull();
    expect(framed.parentElement).toBe(settings.parentElement?.parentElement);
    expect(await within(section).findByRole("table", { name: "Open positions" })).toBeInTheDocument();
  });
});

/** A button that asks for the answer again, as the Strategies page's "Read again" does; the section draws none after a good read. */
function AskAgain() {
  const queryClient = useQueryClient();
  return (
    <button type="button" onClick={() => void queryClient.invalidateQueries({ queryKey: OPEN_POSITIONS_KEY })}>
      ask now
    </button>
  );
}

function positionsRequests(api: ReturnType<typeof stubApi>): number {
  return api.mock.calls.filter(([url]) => String(url).endsWith("/positions/open")).length;
}

describe("the states and the orders (T10; spec 'An Order In Flight Is A Dashed Line Under The Open Positions')", () => {
  it("is headed 'Open positions' and the table is named by that heading", async () => {
    await mountSection(answering([aave()]));

    expect(screen.queryByRole("heading", { level: 2, name: "Open positions" })).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Open positions" })).toBeInTheDocument();
  });

  it("reads 'Reading open positions…' while loading, under its heading, and never 'No open position.'", async () => {
    await mountSection({ kind: "pending" });

    expect(screen.queryByRole("heading", { name: "Open positions" })).toBeInTheDocument();
    expect(screen.queryByRole("status")).toHaveTextContent("Reading open positions…");
    expect(screen.queryByText("No open position.")).not.toBeInTheDocument();
  });

  it("says that the first read failed, in an alert, with 'Read again', and never 'No open position.'", async () => {
    const { api } = await mountSection({ kind: "status", status: 500, body: { detail: "down" } });

    const alert = screen.queryByRole("alert");
    expect(alert).toHaveTextContent("Open positions could not be read. A row without a mark does not mean that nothing is open.");
    expect(alert).toHaveClass("text-loss");
    expect(screen.queryByRole("button", { name: "Read again" })).toBeInTheDocument();
    expect(screen.queryByText("No open position.")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Read again" }));
    await waitFor(() => expect(positionsRequests(api)).toBe(2));
  });

  it("keeps 'Read again' in place and focused, disabled for the screen reader, while it reads again after a failure", async () => {
    const held = failsOnceThenHolds(openState([aave()]));
    stubApi(HEALTH, [], undefined, {}, held.route);
    renderAt(<OpenPositionsSection strategy={strategy()} />);
    await settle();
    const button = screen.getByRole("button", { name: "Read again" });
    button.focus();

    fireEvent.click(button);
    await waitFor(() => expect(held.requests()).toBe(2));

    expect(button).toBeInTheDocument();
    expect(document.activeElement).toBe(button);
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByRole("status")).toHaveTextContent("Reading open positions…");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    fireEvent.click(button);
    await settle();
    expect(held.requests()).toBe(2);

    await act(async () => held.release());
    await settle();
    expect(screen.queryByRole("table")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Read again" })).not.toBeInTheDocument();
  });

  it("refuses a body that is not the answer's shape as an error, never as an empty list", async () => {
    await mountSection({ kind: "ok", body: { positions: [] } });

    expect(screen.queryByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("No open position.")).not.toBeInTheDocument();
  });

  it("keeps the last answer on screen when a refresh fails, and adds the red sentence", async () => {
    const current: { status: number; body: unknown } = { status: 200, body: openState([aave()], [], "2026-10-12T21:38:12Z") };
    const route = (url: string) =>
      url.endsWith("/positions/open") ? Promise.resolve(jsonResponse(current.body, current.status)) : undefined;
    stubApi(HEALTH, [], undefined, {}, route);
    renderAt(
      <>
        <AskAgain />
        <OpenPositionsSection strategy={strategy()} />
      </>,
    );
    await settle();
    expect(screen.queryByRole("table")).toBeInTheDocument();

    current.status = 500;
    current.body = { detail: "down" };
    fireEvent.click(screen.getByRole("button", { name: "ask now" }));

    await waitFor(() => expect(screen.queryByText("Could not be refreshed since 21:38:12 UTC.")).toBeInTheDocument());
    expect(screen.getByText("Could not be refreshed since 21:38:12 UTC.")).toHaveClass("text-loss");
    expect(screen.queryByRole("table")).toBeInTheDocument();
    expect(screen.queryByText("No open position.")).not.toBeInTheDocument();
  });

  it("reads 'No open position.' when the read succeeded and the strategy holds nothing", async () => {
    await mountSection(answering([]));

    expect(screen.queryByText("No open position.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("draws the strategy's orders as lines in a list under the table, and not another strategy's", async () => {
    await mountSection(
      answering(
        [aave({ markets: ["SFPUSDT"], origin: "rehearsal" })],
        [
          openOrder({ strategy_id: ALPHA, market: "SFPUSDT", action: "CLOSE", origin: "rehearsal", submitted_at: "2026-10-12T21:12:00Z" }),
          openOrder({ strategy_id: "22222222-2222-4222-8222-222222222222", market: "OTHERUSDT" }),
          openOrder({ strategy_id: null, market: "NOBODYUSDT" }),
        ],
      ),
    );

    const list = screen.queryByRole("list");
    expect(list).toBeInTheDocument();
    const items = within(list as HTMLElement).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual(["SFPUSDT · order in flight · closing · Dry run · sent 21:12 UTC"]);
    expect(theTable().compareDocumentPosition(list as HTMLElement) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(items[0]?.firstElementChild).toHaveClass("border-dashed", "border-decision");
  });

  it("draws the order under 'No open position.' when the strategy holds no position (example 19b)", async () => {
    await mountSection(
      answering([], [openOrder({ strategy_id: ALPHA, market: "AAVEUSDT", action: "OPEN", origin: "live", submitted_at: "2026-10-12T21:36:00Z" })]),
    );

    const empty = screen.queryByText("No open position.");
    expect(empty).toBeInTheDocument();
    const list = screen.queryByRole("list");
    expect(list).toHaveTextContent("AAVEUSDT · order in flight · opening · Live · sent 21:36 UTC");
    expect((empty as HTMLElement).compareDocumentPosition(list as HTMLElement) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("leaves 'opening'/'closing' and 'sent' out of an undecorated order's line", async () => {
    await mountSection(answering([], [openOrder({ strategy_id: ALPHA, market: "AAVEUSDT", action: null, submitted_at: null, origin: "unknown" })]));

    expect(screen.queryByRole("list")).toHaveTextContent(/^AAVEUSDT · order in flight · origin unknown$/);
  });

  it("writes the sent time of an order of the day before with its date", async () => {
    await mountSection(
      answering([], [openOrder({ strategy_id: ALPHA, market: "AAVEUSDT", action: "OPEN", origin: "live", submitted_at: "2026-10-11T21:12:00Z" })]),
    );

    expect(screen.queryByRole("list")).toHaveTextContent("sent 10/11/2026 21:12 UTC");
  });

  it("draws the orders above the notes and the sentence of the unmatched", async () => {
    await mountSection(answering([aave(), unowned()], [openOrder({ strategy_id: ALPHA })]));

    const list = screen.queryByRole("list") as HTMLElement;
    expect(list).toBeInTheDocument();
    expect(list.compareDocumentPosition(screen.getByText(MATCHED_ONE)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(list.compareDocumentPosition(screen.getByText(NOTE.margin)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("does not wait for the exchange scope: it draws while the pools are still loading", async () => {
    stubApi(HEALTH, [], { kind: "pending" }, {}, undefined, {}, undefined, answering([aave()]));
    renderAt(<OpenPositionsSection strategy={strategy()} />);
    await settle();

    expect(screen.queryByRole("table")).toBeInTheDocument();
  });

  it("asks for the open positions once, and for nothing of a venue", async () => {
    const { api } = await mountSection(answering([aave()]));

    expect(positionsRequests(api)).toBe(1);
    expect(api.unexpected).toEqual([]);
  });
});

describe("an absent figure is a dash with its reason (T10, the first red of op.3)", () => {
  it("draws a dash named 'not recorded' for a null leverage on a position that has its facts, and never 1x", async () => {
    await mountSection(answering([openPosition({ strategy_id: ALPHA, leverage: null })]));

    const cell = onlyRow()[COLUMN.leverage] as HTMLElement;
    expect(cell).toHaveTextContent("not recorded");
    expect(cell).not.toHaveTextContent("1x");
    expect(cell.textContent).toBe("—not recorded");
    expect(within(cell).getByText("—")).toHaveAttribute("aria-hidden", "true");
    expect(within(cell).getByText("not recorded")).toHaveClass("sr-only");
  });

  it("draws 'figures not readable' in EVERY empty cell of a position the facts could not decorate", async () => {
    await mountSection(answering([noFacts()]));

    const cells = onlyRow();
    for (const column of ["opened", "side", "size", "entry", "fees", "margin", "leverage"] as const) {
      expect(cells[COLUMN[column]]?.textContent, column).toBe("—figures not readable");
    }
    expect(cells[COLUMN.pair]).toHaveTextContent("STXUSDT");
  });

  it("draws the Opened cell of a null as a dash, never 'Invalid Date' and never an 'x' alone", async () => {
    await mountSection(answering([noFacts()]));

    const cells = onlyRow();
    const text = cells.map((cell) => cell.textContent).join("|");
    expect(text).not.toContain("Invalid Date");
    expect(text).not.toMatch(/(^|\|)x/);
    expect(cells[COLUMN.opened]?.textContent).toBe("—figures not readable");
    expect(cells[COLUMN.leverage]?.textContent).not.toContain("x");
  });

  it("keeps 'not recorded' for the leverage of a position with facts and writes the facts it has", async () => {
    await mountSection(
      answering([openPosition({ strategy_id: ALPHA, leverage: null, fees: "0.17", margin_granted: "121.8" })]),
    );

    const cells = onlyRow();
    expect(cells[COLUMN.leverage]?.textContent).toBe("—not recorded");
    expect(cells[COLUMN.fees]).toHaveTextContent("0.17");
    expect(cells[COLUMN.margin]).toHaveTextContent("121.8");
  });
});
