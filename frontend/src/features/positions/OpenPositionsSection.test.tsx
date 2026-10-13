import { act, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OpenPositionsSection } from "@/features/positions/OpenPositionsSection";
import type { OpenPosition } from "@/shared/api/positions";
import type { Strategy } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import { jsonResponse, lock, openPosition, openState, renderAt, stubApi, unlock } from "@/test/harness";
import type { OpenPositionsStub } from "@/test/harness";

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
    allocation_percent: "100",
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

function proposal(overrides: Record<string, unknown> = {}) {
  return {
    id: "pppppppp-pppp-4ppp-8ppp-pppppppppppp",
    discrepancy_id: DISCREPANCY,
    allocation_id: ALLOCATION,
    state: "PENDING",
    ...overrides,
  };
}

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

type BookingsAnswer = { kind: "ok"; body: unknown[] } | { kind: "pending" } | { kind: "status"; status: number };

/** Mounts the section over one positions answer and one answer to the pending bookings. */
async function mountWithBookings(position: OpenPosition, bookings: BookingsAnswer, asOf = "2026-10-12T21:40:03Z") {
  const route = (url: string) => {
    if (!url.includes("/reconciliation/bookings")) return undefined;
    if (bookings.kind === "pending") return new Promise<Response>(() => undefined);
    if (bookings.kind === "status") return Promise.resolve(jsonResponse({ detail: "down" }, bookings.status));
    return Promise.resolve(jsonResponse(bookings.body));
  };
  stubApi(HEALTH, [], undefined, {}, route, {}, undefined, answering([position], [], asOf));
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

const LINK = "See the pending decision";
const WORDS = "no booking is proposed";

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
    await mountWithBookings(
      disagreeing({ figures_missing: "UNRESOLVED_SYMBOL", side: null, size: null, entry_price: null, reservation_status: "EXPIRED" }),
      { kind: "ok", body: [proposal()] },
    );

    const subs = subRowsOf(theTable());
    expect(subs).toHaveLength(3);
    expect(within(subs[0] as HTMLElement).getByRole("group", { name: "Venue disagrees, AAVEUSDT" })).toBeInTheDocument();
    expect(subs[1]).toHaveTextContent("The pair's base currency cannot be told");
    expect(subs[2]).toHaveTextContent("Its reservation reads EXPIRED, not FILLED.");
    for (const sub of subs) expect((sub.querySelector("td") as HTMLTableCellElement).colSpan).toBe(8);
  });

  it("draws the venue line, solid red, across the table's width under its row", async () => {
    await mountWithBookings(disagreeing(), { kind: "ok", body: [proposal()] });

    const sub = firstSubRow(theTable());
    const line = within(sub as HTMLElement).getByRole("group", { name: "Venue disagrees, AAVEUSDT" });
    expect(line).toHaveClass("border-loss", "w-full");
    expect(line).not.toHaveClass("border-dashed");
    expect(line.textContent).toBe(
      "AAVEUSDT · venue disagrees · exchange 0 AAVE, ledger 0.82 AAVE · last compared 21:39:12 UTC · See the pending decision",
    );
  });

  it("draws the link when a pending proposal names this allocation and this discrepancy", async () => {
    await mountWithBookings(disagreeing(), { kind: "ok", body: [proposal()] });

    const link = await screen.findByRole("link", { name: `${LINK}, AAVEUSDT` });
    expect(link).toHaveAttribute("href", "/#decision-rail");
    expect(screen.queryByText(WORDS, { exact: false })).not.toBeInTheDocument();
  });

  it.each([
    ["no proposal is pending", []],
    ["the proposal names another discrepancy", [proposal({ discrepancy_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee" })]],
    ["the proposal names another allocation", [proposal({ allocation_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" })]],
    ["the proposal is not pending", [proposal({ state: "REJECTED" })]],
  ])("says that no booking is proposed, and links nowhere, when %s", async (_label, body) => {
    await mountWithBookings(disagreeing(), { kind: "ok", body });

    const sub = firstSubRow(theTable());
    expect(sub).toHaveTextContent(WORDS);
    expect(within(sub as HTMLElement).queryByRole("link")).not.toBeInTheDocument();
  });

  it.each([
    ["the proposals are loading", { kind: "pending" } as BookingsAnswer],
    ["their read failed", { kind: "status", status: 500 } as BookingsAnswer],
  ])("draws neither the link nor the words while %s", async (_label, answer) => {
    await mountWithBookings(disagreeing(), answer);

    const sub = firstSubRow(theTable());
    expect(sub).toHaveTextContent("AAVEUSDT · venue disagrees");
    expect(sub).not.toHaveTextContent(WORDS);
    expect(within(sub as HTMLElement).queryByRole("link")).not.toBeInTheDocument();
  });

  it("writes 'last compared' with its date when the instant is of the day before the answer's", async () => {
    await mountWithBookings(
      disagreeing({
        venue_disagreement: {
          discrepancy_id: DISCREPANCY,
          venue_net_base: "0",
          ledger_net_base: "0.82",
          allocation_count: 1,
          last_observed_at: "2026-10-11T21:12:00Z",
        },
      }),
      { kind: "ok", body: [] },
    );

    const sub = firstSubRow(theTable());
    expect(sub).toHaveTextContent("last compared 10/11/2026 21:12:00 UTC");
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
