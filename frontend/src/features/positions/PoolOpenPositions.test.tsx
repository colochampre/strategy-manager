import { useQueryClient } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OpenPositionsSection } from "@/features/positions/OpenPositionsSection";
import { ORIGIN_STYLE } from "@/features/positions/origin";
import { PoolOpenPositions } from "@/features/positions/PoolOpenPositions";
import { OPEN_POSITIONS_KEY } from "@/shared/api/positions";
import type { OpenPool, OpenPosition } from "@/shared/api/positions";
import type { Strategy } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import { failsOnceThenHolds, jsonResponse, lock, openOrder, openPosition, openState, renderAt, setViewport, stubApi, unlock } from "@/test/harness";
import type { OpenPositionsStub } from "@/test/harness";

/**
 * T13, the list half (design addendum § H, the Overview part; spec "The Overview Lists Every Open Position Of
 * The Selected Exchange, Pool By Pool"): examples 22 and 24, and the Spanish of 25.
 */

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const SFP = "11111111-1111-4111-8111-111111111111";
const STX = "22222222-2222-4222-8222-222222222222";

const USDT_POOL: OpenPool = { exchange: "bybit", venue: "usdt-m", settlement_currency: "USDT" };
/** The same exchange and venue in another settlement currency, and the same currency on another venue: never this pool. */
const USDC_POOL: OpenPool = { exchange: "bybit", venue: "usdt-m", settlement_currency: "USDC" };
const SPOT_POOL: OpenPool = { exchange: "bybit", venue: "spot", settlement_currency: "USDT" };
const BTC_POOL: OpenPool = { exchange: "bybit", venue: "inverse", settlement_currency: "BTC" };
const OTHER_EXCHANGE_POOL: OpenPool = { exchange: "binance", venue: "usdt-m", settlement_currency: "USDT" };

beforeEach(async () => {
  unlock();
  setViewport("wide");
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

/** A strategy of the same pool, for the detail section that shares the request. */
function strategy(): Strategy {
  return {
    id: SFP,
    name: "SFP 4h - RSI Divergences",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    subscription: null,
    enabled: true,
    archived_at: null,
    allowed_pairs: ["SFPUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    visibility: "PRIVATE",
  };
}

/** A button that asks the open positions again, as the window focus or the 60 s poll does. */
function AskAgain() {
  const queryClient = useQueryClient();
  return (
    <button type="button" onClick={() => void queryClient.invalidateQueries({ queryKey: OPEN_POSITIONS_KEY })}>
      ask now
    </button>
  );
}

const answering = (...args: Parameters<typeof openState>): OpenPositionsStub => ({ kind: "ok", body: openState(...args) });

async function mountList(openPositions: OpenPositionsStub, pool: OpenPool = USDT_POOL, bookings: unknown[] = []) {
  const api = stubApi(HEALTH, bookings, undefined, {}, undefined, {}, undefined, openPositions);
  const view = renderAt(<PoolOpenPositions pool={pool} />);
  await settle();
  return { api, view };
}

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

const COLUMN = { strategy: 0, opened: 1, pair: 2, side: 3, size: 4, entry: 5, margin: 6, leverage: 7 } as const;

function onlyRow(): HTMLElement[] {
  const rows = positionRows(theTable());
  expect(rows).toHaveLength(1);
  return cellsOf(rows[0] as HTMLElement);
}

/** What each position row of the table shows in its Pair cell, without the origin's word. */
function pairsOfTable(): string[] {
  const table = theTable();
  // Found by its heading, so that a missing or extra column cannot make this read another column's text.
  const at = within(table)
    .getAllByRole("columnheader")
    .findIndex((heading) => heading.textContent === "Pair");
  return positionRows(table).map((row) => (cellsOf(row)[at]?.firstChild?.textContent ?? "").trim());
}

/** A position of a strategy in a pool, with a pair of its own. */
function held(pair: string, pool: OpenPool = USDT_POOL, overrides: Partial<OpenPosition> = {}): OpenPosition {
  return openPosition({
    strategy_id: SFP,
    strategy_name: "SFP 4h - RSI Divergences",
    pool,
    currency: pool.settlement_currency,
    markets: [pair],
    base_currency: pair.replace(/USDT$|USDC$|USD$/, ""),
    ...overrides,
  });
}

/** A position the facts could not decorate: every nullable field is null (design § F). */
function noFacts(overrides: Partial<OpenPosition> = {}): OpenPosition {
  return openPosition({
    strategy_id: null,
    strategy_name: "Unattributed",
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
  return held("AAVEUSDT", USDT_POOL, {
    strategy_id: STX,
    strategy_name: "STX 4h - RSI Divergences",
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

describe("the list is the pool's own (T13; rule 7)", () => {
  it("draws no position of another pool of the same exchange", async () => {
    await mountList(
      answering([
        held("AAVEUSDT", USDT_POOL),
        held("SUIUSDT", USDC_POOL),
        held("LINKUSDT", SPOT_POOL),
        held("BTCUSD", BTC_POOL),
        held("ETHUSDT", OTHER_EXCHANGE_POOL),
      ]),
    );

    expect(pairsOfTable()).toEqual(["AAVEUSDT"]);
    for (const other of ["SUIUSDT", "LINKUSDT", "BTCUSD", "ETHUSDT"]) {
      expect(screen.queryByText(other), other).not.toBeInTheDocument();
    }
  });

  it("selects by the three values of the pool: the same exchange and venue in another currency is not it", async () => {
    await mountList(answering([held("AAVEUSDT", USDT_POOL), held("SUIUSDT", USDC_POOL)]), USDC_POOL);

    expect(pairsOfTable()).toEqual(["SUIUSDT"]);
  });

  it("keeps the order the server sent, and writes no sum across rows", async () => {
    await mountList(answering([held("ZZZUSDT", USDT_POOL), held("AAAUSDT", USDT_POOL), held("MMMUSDT", USDT_POOL)]));

    expect(pairsOfTable()).toEqual(["ZZZUSDT", "AAAUSDT", "MMMUSDT"]);
  });
});

describe("the columns and the cells (T13; example 22)", () => {
  it("has eight columns, the strategy first, and no Fees column", async () => {
    await mountList(answering([aave()]));

    const headings = within(theTable())
      .getAllByRole("columnheader")
      .map((heading) => heading.textContent);
    expect(headings).toEqual([
      "Strategy",
      "Opened (UTC)",
      "Pair",
      "Side",
      "Size",
      "Entry",
      "Margin granted USDT",
      "Leverage",
    ]);
    expect(screen.queryByText(/^Fees/)).not.toBeInTheDocument();
    expect(cellsOf(positionRows(theTable())[0] as HTMLElement)).toHaveLength(8);
  });

  it("writes a live position's figures under their columns, with its origin in the Pair cell", async () => {
    await mountList(answering([aave()]));

    const cells = onlyRow();
    expect(cells[COLUMN.strategy]).toHaveTextContent("STX 4h - RSI Divergences");
    expect(cells[COLUMN.opened]).toHaveTextContent("10/11/2026");
    expect(cells[COLUMN.pair]).toHaveTextContent("AAVEUSDTLive");
    expect(cells[COLUMN.side]).toHaveTextContent("LONG");
    expect(cells[COLUMN.size]).toHaveTextContent("0.82 AAVE");
    expect(cells[COLUMN.entry]).toHaveTextContent("184.3");
    expect(cells[COLUMN.margin]?.textContent).toBe("121.80");
    expect(cells[COLUMN.leverage]?.textContent).toBe("2x");
  });

  it("lists dry-run and live positions together, each with its own origin", async () => {
    await mountList(answering([held("SFPUSDT", USDT_POOL, { origin: "rehearsal" }), held("STXUSDT", USDT_POOL, { origin: "live" })]));

    const rows = positionRows(theTable());
    expect(cellsOf(rows[0] as HTMLElement)[COLUMN.pair]).toHaveTextContent("SFPUSDTDry run");
    expect(cellsOf(rows[1] as HTMLElement)[COLUMN.pair]).toHaveTextContent("STXUSDTLive");
  });

  it("draws no note under the list, whatever the origins", async () => {
    await mountList(answering([held("SFPUSDT", USDT_POOL, { origin: "rehearsal" }), held("STXUSDT", USDT_POOL, { origin: "mixed" })]));

    expect(screen.queryByText(/dry-run position was filled/)).not.toBeInTheDocument();
    expect(screen.queryByText(/holds dry-run and live fills/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Margin granted is what the share took/)).not.toBeInTheDocument();
  });

  it("draws no order in flight (owner decision Q8, 2026-10-13), not even one of this pool", async () => {
    await mountList(
      answering(
        [aave()],
        [openOrder({ pool: USDT_POOL, market: "ORDERUSDT", strategy_id: STX }), openOrder({ pool: USDT_POOL, market: "SOLUSDT", strategy_id: null })],
      ),
    );

    expect(screen.queryByText(/order in flight/)).not.toBeInTheDocument();
    expect(screen.queryByText(/ORDERUSDT/)).not.toBeInTheDocument();
    expect(screen.queryAllByRole("list")).toHaveLength(0);
  });
});

describe("the strategy's name (T13)", () => {
  it("is a link to the strategy's page when the row has a strategy id", async () => {
    await mountList(answering([aave()]));

    const link = within(onlyRow()[COLUMN.strategy] as HTMLElement).getByRole("link", { name: "STX 4h - RSI Divergences" });
    expect(link).toHaveAttribute("href", `/strategies/${STX}`);
  });

  it("is plain text when the row has no strategy id", async () => {
    await mountList(answering([noFacts()]));

    const cell = onlyRow()[COLUMN.strategy] as HTMLElement;
    expect(cell).toHaveTextContent("Unattributed");
    expect(within(cell).queryByRole("link")).not.toBeInTheDocument();
  });
});

describe("a position the facts could not decorate (T13; K row 10)", () => {
  it("is a row whose six figures are each a dash named 'figures not readable'", async () => {
    await mountList(answering([noFacts()]));

    const cells = onlyRow();
    for (const column of ["opened", "side", "size", "entry", "margin", "leverage"] as const) {
      expect(cells[COLUMN[column]]?.textContent, column).toBe("—figures not readable");
    }
    expect(cells[COLUMN.pair]).toHaveTextContent("STXUSDT");
  });

  it("writes no 'Invalid Date' and no 'x' alone", async () => {
    await mountList(answering([noFacts()]));

    const text = theTable().textContent ?? "";
    expect(text).not.toContain("Invalid Date");
    expect(onlyRow()[COLUMN.leverage]?.textContent).not.toBe("x");
    expect(text).not.toMatch(/(^|[^\w])x($|[^\w])/);
  });
});

describe("the venue line under its row (T13; spec 'On The Detail Page And The Overview The Venue Mark Is One Solid Red Line')", () => {
  it("is drawn under its row, as the table's own sub-row across the eight columns", async () => {
    await mountList(
      answering([
        aave({
          venue_disagreement: {
            discrepancy_id: "d-1",
            venue_net_base: "0",
            ledger_net_base: "0.82000000",
            allocation_count: 1,
            last_observed_at: "2026-10-12T21:39:12Z",
          },
        }),
      ]),
    );

    const table = theTable();
    const rows = within(table).getAllByRole("row");
    const own = positionRows(table)[0] as HTMLElement;
    const after = rows[rows.indexOf(own) + 1] as HTMLElement;
    expect(after.querySelectorAll("td")).toHaveLength(1);
    expect(after.querySelector("td")).toHaveAttribute("colspan", "8");
    const line = within(after).getByRole("group", { name: "Venue disagrees, AAVEUSDT" });
    expect(line).toHaveClass("border-solid", "border-loss");
  });
});

describe("the states (T13; K row 21)", () => {
  it("draws the heading and names the table by it", async () => {
    await mountList(answering([aave()]));

    expect(screen.queryByRole("heading", { level: 2, name: "Open positions" })).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Open positions" })).toBeInTheDocument();
  });

  it("reads 'Reading open positions…' while loading, under its heading, and never 'No open position.'", async () => {
    await mountList({ kind: "pending" });

    expect(screen.queryByRole("heading", { name: "Open positions" })).toBeInTheDocument();
    expect(screen.queryByRole("status")).toHaveTextContent("Reading open positions…");
    expect(screen.queryByText("No open position.")).not.toBeInTheDocument();
  });

  it("says in an alert that the read failed, with 'Read again', and never 'No open position.'", async () => {
    const { api } = await mountList({ kind: "status", status: 500, body: { detail: "down" } });

    expect(screen.queryByRole("heading", { name: "Open positions" })).toBeInTheDocument();
    const alert = screen.queryByRole("alert");
    expect(alert).toHaveTextContent("Open positions could not be read. A row without a mark does not mean that nothing is open.");
    expect(alert).toHaveClass("text-loss");
    expect(screen.queryByText("No open position.")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Read again" }));
    await waitFor(() => expect(api.mock.calls.filter(([url]) => String(url).endsWith("/positions/open"))).toHaveLength(2));
  });

  it("keeps 'Read again' in place and focused, disabled for the screen reader, while it reads again after a failure", async () => {
    const route = failsOnceThenHolds(openState([held("SFPUSDT")]));
    stubApi(HEALTH, [], undefined, {}, route.route);
    renderAt(<PoolOpenPositions pool={USDT_POOL} />);
    await settle();
    const button = screen.getByRole("button", { name: "Read again" });
    button.focus();

    fireEvent.click(button);
    await waitFor(() => expect(route.requests()).toBe(2));

    expect(button).toBeInTheDocument();
    expect(document.activeElement).toBe(button);
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByRole("status")).toHaveTextContent("Reading open positions…");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    fireEvent.click(button);
    await settle();
    expect(route.requests()).toBe(2);

    await act(async () => route.release());
    await settle();
    expect(screen.queryByRole("table")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Read again" })).not.toBeInTheDocument();
  });

  it("reads a body that is not the answer's shape as a failure, never as an empty list", async () => {
    await mountList({ kind: "ok", body: { positions: [] } });

    expect(screen.queryByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("No open position.")).not.toBeInTheDocument();
  });

  it("reads 'No open position.' under the heading when the read succeeded and this pool holds nothing", async () => {
    await mountList(answering([held("SUIUSDT", USDC_POOL)]));

    expect(screen.queryByRole("heading", { name: "Open positions" })).toBeInTheDocument();
    expect(screen.queryByText("No open position.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps the last answer when a refresh fails, and says since when in red", async () => {
    const current: { status: number; body: unknown } = { status: 200, body: openState([aave()], [], "2026-10-12T21:38:12Z") };
    const route = (url: string) =>
      url.endsWith("/positions/open") ? Promise.resolve(jsonResponse(current.body, current.status)) : undefined;
    stubApi(HEALTH, [], undefined, {}, route);
    renderAt(
      <>
        <AskAgain />
        <PoolOpenPositions pool={USDT_POOL} />
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
});

describe("below md the positions are cards (T13; N2)", () => {
  beforeEach(() => setViewport("narrow"));

  const TWO = [
    aave(),
    held("SFPUSDT", USDT_POOL, {
      origin: "rehearsal",
      side: "SHORT",
      base_currency: "SFP",
      size: "300",
      opened_size: "300",
      entry_price: "0.4212",
      margin_granted: "126.36",
      leverage: "1.00000000",
      opened_at: "2026-10-10T08:00:00Z",
    }),
  ];

  it("renders one article per position and no table", async () => {
    await mountList(answering(TWO));

    expect(screen.queryAllByRole("article")).toHaveLength(2);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("names each card by its pair and side", async () => {
    await mountList(answering(TWO));

    expect(screen.queryAllByRole("article").map((card) => card.getAttribute("aria-label"))).toEqual(["AAVEUSDT LONG", "SFPUSDT SHORT"]);
  });

  it("puts the strategy's name, a link, under the card's head", async () => {
    await mountList(answering(TWO));

    const [card] = screen.queryAllByRole("article") as [HTMLElement];
    const parts = [...card.children];
    expect(parts[0]).toHaveTextContent("AAVEUSDTLONGLive");
    const link = within(parts[1] as HTMLElement).getByRole("link", { name: "STX 4h - RSI Divergences" });
    expect(link).toHaveAttribute("href", `/strategies/${STX}`);
    expect(parts[2]?.tagName).toBe("DL");
  });

  it("carries five labelled values and no Fees", async () => {
    await mountList(answering(TWO));

    const [card] = screen.queryAllByRole("article") as [HTMLElement];
    const values = Object.fromEntries(
      [...card.querySelectorAll("dl > div")].map((pair) => [pair.querySelector("dt")?.textContent ?? "", pair.querySelector("dd")?.textContent ?? ""]),
    );
    expect(values).toEqual({
      "Opened (UTC)": "10/11/2026 14:05",
      Size: "0.82 AAVE",
      Entry: "184.3",
      "Margin granted USDT": "121.80",
      Leverage: "2x",
    });
  });

  it("writes the name of a row with no strategy id as plain text", async () => {
    await mountList(answering([noFacts()]));

    const [card] = screen.queryAllByRole("article") as [HTMLElement];
    expect(card).toHaveTextContent("Unattributed");
    expect(within(card).queryByRole("link")).not.toBeInTheDocument();
  });
});

describe("the origin's tag comes from origin.ts (T21, the Overview's half)", () => {
  it.each(["rehearsal", "live", "mixed"] as const)("draws a %s position's tag with the table's text key and class", async (origin) => {
    await mountList(answering([held("AAVEUSDT", USDT_POOL, { origin })]));

    const cell = onlyRow()[COLUMN.pair] as HTMLElement;
    const style = ORIGIN_STYLE[origin];
    const tag = within(cell).getByText(String(i18n.t(style.textKey)));
    expect(tag).toHaveClass(style.text);
    // A dry-run tag is amber, a live one cyan, and a position of both origins red: three different words and colours.
    expect(new Set([ORIGIN_STYLE.rehearsal.text, ORIGIN_STYLE.live.text, ORIGIN_STYLE.mixed.text]).size).toBe(3);
  });

  it("draws the card's tag the same way", async () => {
    setViewport("narrow");
    await mountList(answering([held("SFPUSDT", USDT_POOL, { origin: "rehearsal" })]));

    const [card] = screen.queryAllByRole("article") as [HTMLElement];
    expect(within(card).getByText("Dry run")).toHaveClass(ORIGIN_STYLE.rehearsal.text);
  });
});

describe("it shares one request with the other places (T22, the Overview's half)", () => {
  function requestsFor(api: ReturnType<typeof stubApi>): number {
    return api.mock.calls.filter(([url]) => String(url).endsWith("/positions/open")).length;
  }

  it("asks once for two pools of the Overview", async () => {
    const api = stubApi(HEALTH, [], undefined, {}, undefined, {}, undefined, answering([held("AAVEUSDT"), held("BTCUSD", BTC_POOL)]));
    renderAt(
      <>
        <PoolOpenPositions pool={USDT_POOL} />
        <PoolOpenPositions pool={BTC_POOL} />
      </>,
    );
    await settle();

    expect(requestsFor(api)).toBe(1);
    expect(api.unexpected).toEqual([]);
  });

  it("asks once when the Overview's list and the detail page's section are both on screen", async () => {
    const api = stubApi(HEALTH, [], undefined, {}, undefined, {}, undefined, answering([held("AAVEUSDT")]));
    renderAt(
      <>
        <PoolOpenPositions pool={USDT_POOL} />
        <OpenPositionsSection strategy={strategy()} />
      </>,
    );
    await settle();

    expect(requestsFor(api)).toBe(1);
  });
});

describe("in Spanish (T10 and T11; owner decision Q9, 2026-10-13)", () => {
  beforeEach(async () => {
    await act(() => i18n.changeLanguage("es"));
  });

  it("writes the headings, the list's name and the fixed Spanish of section I", async () => {
    await mountList(answering([aave()]));

    expect(screen.queryByRole("heading", { level: 2, name: "Posiciones abiertas" })).toBeInTheDocument();
    const headings = within(screen.getByRole("table", { name: "Posiciones abiertas" }))
      .getAllByRole("columnheader")
      .map((heading) => heading.textContent);
    expect(headings).toEqual([
      "Estrategia",
      "Apertura (UTC)",
      "Par",
      "Sentido",
      "Tamaño",
      "Entrada",
      "Margen otorgado USDT",
      "Apalancamiento",
    ]);
  });

  it("writes a price and a size with a POINT and money with the language's separator, as the detail section does", async () => {
    await mountList(answering([aave()]));

    const cells = onlyRow();
    expect(cells[COLUMN.size]?.textContent).toBe("0.82 AAVE");
    expect(cells[COLUMN.entry]?.textContent).toBe("184.3");
    expect(cells[COLUMN.margin]?.textContent).toBe("121,80");
    expect(cells[COLUMN.leverage]?.textContent).toBe("2x");
    expect(cells[COLUMN.pair]).toHaveTextContent("AAVEUSDTEn vivo");
  });

  it("writes the card's labels and values in Spanish, the strategy's name under the head", async () => {
    setViewport("narrow");
    await mountList(answering([aave()]));

    const [card] = screen.queryAllByRole("article") as [HTMLElement];
    const values = Object.fromEntries(
      [...card.querySelectorAll("dl > div")].map((pair) => [pair.querySelector("dt")?.textContent ?? "", pair.querySelector("dd")?.textContent ?? ""]),
    );
    expect(values).toEqual({
      "Apertura (UTC)": "11/10/2026 14:05",
      Tamaño: "0.82 AAVE",
      Entrada: "184.3",
      "Margen otorgado USDT": "121,80",
      Apalancamiento: "2x",
    });
    expect(card.children[1]).toHaveTextContent("STX 4h - RSI Divergences");
  });

  it("reads its states in Spanish", async () => {
    await mountList(answering([]));
    expect(screen.queryByText("Sin posiciones abiertas.")).toBeInTheDocument();
  });

  it("reads the loading and the failed states in Spanish, with 'Leer de nuevo'", async () => {
    await mountList({ kind: "status", status: 500, body: { detail: "down" } });

    expect(screen.queryByRole("alert")).toHaveTextContent("No se pudieron leer las posiciones abiertas.");
    expect(screen.queryByRole("button", { name: "Leer de nuevo" })).toBeInTheDocument();
  });

  it("writes the dash's reason in Spanish, in the sr-only text of each cell", async () => {
    await mountList(answering([noFacts()]));

    const cell = onlyRow()[COLUMN.size] as HTMLElement;
    expect(cell.textContent).toBe("—cifras no legibles");
    expect(within(cell).getByText("—")).toHaveAttribute("aria-hidden", "true");
    expect(within(cell).getByText("cifras no legibles")).toHaveClass("sr-only");
  });
});

describe("the dashes carry their reason for a screen reader (T13)", () => {
  it("hides the dash itself and gives the reason in sr-only text, in the table and in the card", async () => {
    await mountList(answering([noFacts()]));

    for (const column of ["opened", "side", "size", "entry", "margin", "leverage"] as const) {
      const cell = onlyRow()[COLUMN[column]] as HTMLElement;
      expect(within(cell).getByText("—"), column).toHaveAttribute("aria-hidden", "true");
      expect(within(cell).getByText("figures not readable"), column).toHaveClass("sr-only");
    }
  });

  it("does the same in the card", async () => {
    setViewport("narrow");
    await mountList(answering([noFacts()]));

    const [card] = screen.queryAllByRole("article") as [HTMLElement];
    expect(card.getAttribute("aria-label")).toBe("STXUSDT side not readable");
    const reasons = within(card).getAllByText("figures not readable");
    // The side in the head and the five labelled values.
    expect(reasons).toHaveLength(6);
    for (const reason of reasons) expect(reason).toHaveClass("sr-only");
  });
});
