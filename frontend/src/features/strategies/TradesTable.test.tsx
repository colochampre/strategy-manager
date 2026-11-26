import { fireEvent, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TradesTable } from "@/features/strategies/TradesTable";
import type { StrategyTrade, StrategyTradesPage } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { jsonResponse, lock, renderAt, stubApi, unlock } from "@/test/harness";
import { pressEnter, pressSpace, pressTab } from "@/test/keyboard";

const ID = "11111111-1111-4111-8111-111111111111";
const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;

function trade(n: number, overrides: Partial<StrategyTrade> = {}): StrategyTrade {
  const id = `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
  return {
    allocation_id: id,
    pair: "SOLUSDT",
    direction: "LONG",
    opened_at: `2026-09-${String(30 - n).padStart(2, "0")}T10:00:00Z`,
    closed_at: `2026-09-${String(30 - n).padStart(2, "0")}T12:30:00.${String(n).padStart(6, "0")}Z`,
    rehearsal: false,
    rehearsal_fill_price: null,
    base_currency: "SOL",
    entry_price: "0.451200000000000000",
    exit_price: "0.463100000000000000",
    size: "1250.000000000000000000",
    fees: "0.63",
    other_fees: [],
    pnl: `${n}.50`,
    capital_at_open: "1000.00",
    return: "0.0015000000",
    fees_complete: true,
    ...overrides,
  };
}

interface Server {
  requests: URL[];
  /** Answers a failure for the next request that carries a cursor. */
  failNextCursorRequest: () => void;
}

/**
 * A keyset server: pages of `size` newest first, the cursor is the last row served, and a request
 * with a cursor continues strictly after the row that cursor names. A wrong cursor serves wrong rows.
 */
function serve(all: readonly StrategyTrade[], size: number, first?: () => Promise<Response>): Server {
  const requests: URL[] = [];
  let failNext = false;
  stubApi(HEALTH, [], undefined, {}, (url) => {
    const parsed = new URL(url, "http://localhost");
    if (!/\/performance\/strategies\/[^/]+\/trades$/.test(parsed.pathname)) return undefined;
    requests.push(parsed);
    const after = parsed.searchParams.get("before_allocation_id");
    if (after === null && first !== undefined) return first();
    if (after !== null && failNext) {
      failNext = false;
      return Promise.resolve(jsonResponse({ detail: "boom" }, 500));
    }
    const start = after === null ? 0 : all.findIndex((entry) => entry.allocation_id === after) + 1;
    const rows = all.slice(start, start + size);
    const last = rows[rows.length - 1];
    const more = start + size < all.length;
    const page: StrategyTradesPage = {
      trades: [...rows],
      next_cursor:
        more && last !== undefined
          ? { before_closed_at: last.closed_at, before_allocation_id: last.allocation_id }
          : null,
      total: all.length,
    };
    return Promise.resolve(jsonResponse(page));
  });
  return {
    requests,
    failNextCursorRequest: () => {
      failNext = true;
    },
  };
}

function renderTable(currency = "USDT") {
  renderAt(<TradesTable strategyId={ID} currency={currency} />);
}

const bodyRows = () => {
  const body = screen.getAllByRole("rowgroup")[1] as HTMLElement;
  return within(body).getAllByRole("row");
};
const next = () => screen.getByRole("button", { name: i18n.t("strategies.performance.trades.next") });
const previous = () => screen.getByRole("button", { name: i18n.t("strategies.performance.trades.previous") });
const pageLabel = (page: number) => i18n.t("strategies.performance.trades.page", { page });
/** The columns' names in order, written in words. */
const headerNames = () => screen.getAllByRole("columnheader").map((header) => header.textContent);
const pnls = () => bodyRows().map((row) => within(row).getAllByRole("cell")[8]?.textContent);

beforeEach(unlock);
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

describe("TradesTable", () => {
  // Was test_infinite_query_keyset_cursor_loads_more_on_scroll_or_click: the list no longer accumulates.
  it("test_keyset_paging_shows_one_page_at_a_time_and_next_asks_the_server_with_the_cursor", async () => {
    const all = [1, 2, 3, 4, 5].map((n) => trade(n));
    const server = serve(all, 2);
    renderTable();

    await screen.findByRole("table");
    expect(pnls()).toEqual(["+1.50", "+2.50"]);
    expect(screen.getByText(pageLabel(1))).toBeInTheDocument();
    expect(server.requests).toHaveLength(1);

    fireEvent.click(next());
    await screen.findByText(pageLabel(2));
    // One page on screen, never the accumulated list.
    expect(pnls()).toEqual(["+3.50", "+4.50"]);

    fireEvent.click(next());
    await screen.findByText(pageLabel(3));
    expect(pnls()).toEqual(["+5.50"]);
    expect(server.requests).toHaveLength(3);
  });

  it("test_previous_uses_the_pages_already_loaded_and_sends_nothing", async () => {
    const all = [1, 2, 3, 4, 5].map((n) => trade(n));
    const server = serve(all, 2);
    renderTable();
    await screen.findByRole("table");
    fireEvent.click(next());
    await screen.findByText(pageLabel(2));
    fireEvent.click(next());
    await screen.findByText(pageLabel(3));
    expect(server.requests).toHaveLength(3);

    fireEvent.click(previous());
    expect(screen.getByText(pageLabel(2))).toBeInTheDocument();
    expect(pnls()).toEqual(["+3.50", "+4.50"]);
    fireEvent.click(previous());
    expect(pnls()).toEqual(["+1.50", "+2.50"]);
    // Going forward again over loaded pages asks for nothing either.
    fireEvent.click(next());
    expect(pnls()).toEqual(["+3.50", "+4.50"]);
    fireEvent.click(next());
    expect(pnls()).toEqual(["+5.50"]);

    expect(server.requests).toHaveLength(3);
  });

  it("disables Previous on the first page and Next on the last, where the cursor is null", async () => {
    serve([1, 2, 3].map((n) => trade(n)), 2);
    renderTable();
    await screen.findByRole("table");

    expect(previous()).toBeDisabled();
    expect(next()).toBeEnabled();

    fireEvent.click(next());
    await screen.findByText(pageLabel(2));

    expect(next()).toBeDisabled();
    expect(previous()).toBeEnabled();
  });

  it("sends each next request the exact cursor the server answered, and never an offset", async () => {
    const all = [1, 2, 3, 4, 5].map((n) => trade(n));
    const server = serve(all, 2);
    renderTable();
    await screen.findByRole("table");

    fireEvent.click(next());
    await screen.findByText(pageLabel(2));
    fireEvent.click(next());
    await screen.findByText(pageLabel(3));

    const [firstRequest, secondRequest, thirdRequest] = server.requests;
    expect(firstRequest?.searchParams.has("before_closed_at")).toBe(false);
    expect(firstRequest?.searchParams.has("before_allocation_id")).toBe(false);
    expect(secondRequest?.searchParams.get("before_closed_at")).toBe(all[1]?.closed_at);
    expect(secondRequest?.searchParams.get("before_allocation_id")).toBe(all[1]?.allocation_id);
    expect(thirdRequest?.searchParams.get("before_closed_at")).toBe(all[3]?.closed_at);
    expect(thirdRequest?.searchParams.get("before_allocation_id")).toBe(all[3]?.allocation_id);
    for (const request of server.requests) {
      expect([...request.searchParams.keys()].filter((key) => /offset|page|skip/i.test(key))).toEqual([]);
    }
  });

  it("asks the server for 20 rows a page", async () => {
    const server = serve([trade(1)], 5);
    renderTable();

    await screen.findByRole("table");

    expect(server.requests[0]?.searchParams.get("limit")).toBe("20");
  });

  it("shows the page number and no page count, since the server serves no total", async () => {
    serve([1, 2, 3].map((n) => trade(n)), 2);
    renderTable();

    await screen.findByRole("table");

    expect(screen.getByText(pageLabel(1)).textContent).toBe("Page 1");
    expect(screen.queryByText(/\bof\b/i)).toBeNull();
  });

  // Was "shows no load-more button when the first page is the whole list".
  it("has both buttons disabled when the first page is the whole list", async () => {
    serve([trade(1), trade(2)], 5);
    renderTable();

    await screen.findByRole("table");

    expect(bodyRows()).toHaveLength(2);
    expect(previous()).toBeDisabled();
    expect(next()).toBeDisabled();
  });

  // Was "disables the button and says it is loading while the next page is on its way".
  it("disables Next and says it is loading while the next page is on its way, keeping the page", async () => {
    const all = [1, 2, 3].map((n) => trade(n));
    serve(all, 2);
    renderTable();
    await screen.findByRole("table");
    const fetchMock = vi.mocked(fetch);
    const realImplementation = fetchMock.getMockImplementation();
    fetchMock.mockImplementation((input, init) =>
      String(input).includes("before_allocation_id") ? new Promise<Response>(() => undefined) : (realImplementation?.(input, init) as Promise<Response>),
    );

    fireEvent.click(next());

    const busy = await screen.findByRole("button", { name: i18n.t("strategies.performance.trades.loadingMore") });
    expect(busy).toBeDisabled();
    expect(screen.getByText(pageLabel(1))).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(2);
  });

  // Was "keeps the rows already loaded and says the next page failed, then loads it on a second click".
  it("keeps the current page on screen and says the next page failed, then moves on at a second click", async () => {
    const all = [1, 2, 3, 4].map((n) => trade(n));
    const server = serve(all, 2);
    renderTable();
    await screen.findByRole("table");
    server.failNextCursorRequest();

    fireEvent.click(next());

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.performance.trades.nextFailed"));
    expect(screen.getByText(pageLabel(1))).toBeInTheDocument();
    expect(pnls()).toEqual(["+1.50", "+2.50"]);

    fireEvent.click(next());
    await screen.findByText(pageLabel(2));
    expect(pnls()).toEqual(["+3.50", "+4.50"]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("starts again at page 1 when the page is shown for another strategy", async () => {
    serve([1, 2, 3, 4].map((n) => trade(n)), 2);
    function Switcher() {
      const [id, setId] = useState(ID);
      return (
        <>
          <button type="button" onClick={() => setId("22222222-2222-4222-8222-222222222222")}>
            switch
          </button>
          <TradesTable strategyId={id} currency="USDT" />
        </>
      );
    }
    renderAt(<Switcher />);
    await screen.findByRole("table");
    fireEvent.click(next());
    await screen.findByText(pageLabel(2));

    fireEvent.click(screen.getByRole("button", { name: "switch" }));

    expect(await screen.findByText(pageLabel(1))).toBeInTheDocument();
    expect(screen.queryByText(pageLabel(2))).toBeNull();
  });

  it("says the first page failed and offers to try again, with no table", async () => {
    let failing = true;
    const all = [trade(1)];
    serve(all, 5, () =>
      failing
        ? Promise.resolve(jsonResponse({ detail: "boom" }, 500))
        : Promise.resolve(jsonResponse({ trades: all, next_cursor: null, total: 1 })),
    );
    renderTable();

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.performance.trades.error"));
    expect(screen.queryByRole("table")).toBeNull();

    failing = false;
    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.performance.trades.retry") }));

    await screen.findByRole("table");
    expect(bodyRows()).toHaveLength(1);
  });

  it("reads a body that is not a page of trades as a failure, and draws no row", async () => {
    serve([], 5, () => Promise.resolve(jsonResponse({ trades: [{ ...trade(1), pnl: 4.2 }], next_cursor: null, total: 1 })));
    renderTable();

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.performance.trades.error"));
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText("4.20")).toBeNull();
  });

  it("says there are no closed trades yet for an empty list", async () => {
    serve([], 5);
    renderTable();

    expect(await screen.findByText(i18n.t("strategies.performance.trades.empty"))).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button", { name: i18n.t("strategies.performance.trades.next") })).toBeNull();
  });

  // Replaces "shows what the endpoint serves and no entry price, exit price, size or fees column (decision 43, pending)".
  // Heading of the capital column shortened to "Pool at open" (owner decision 46); the list below is the replaced expectation.
  it("shows twelve columns in the order Opened, Closed, Pair, Side, Entry, Exit, Size, Fees USDT, PnL USDT, PnL %, Pool at open, Details", async () => {
    serve([trade(1)], 5);
    renderTable();

    await screen.findByRole("table");

    expect(headerNames()).toEqual([
      "Opened (UTC)",
      "Closed (UTC)",
      "Pair",
      "Side",
      "Entry",
      "Exit",
      "Size",
      "Fees USDT",
      "PnL USDT",
      "PnL %",
      "Pool at open",
      "Details",
    ]);
  });

  it("gives each column its width tier, on the th and on the td", async () => {
    serve([trade(1)], 5);
    renderTable();
    await screen.findByRole("table");

    // Tailwind viewport variants: jsdom has no layout, so the tier is read from the classes.
    const tier = (element: Element | undefined) => {
      const classes = [...(element?.classList ?? [])];
      if (!classes.includes("hidden")) return "always";
      return classes.find((name) => name.endsWith(":table-cell")) ?? "hidden";
    };
    const expected = [
      "min-[90rem]:table-cell",
      "always",
      "always",
      "always",
      "md:table-cell",
      "md:table-cell",
      // At 13 px, like the other tables (L32), Size and Pool at open wait for a wider screen; both are in the detail.
      "min-[105rem]:table-cell",
      "xl:table-cell",
      "always",
      "always",
      "min-[105rem]:table-cell",
      "always",
    ];

    const headers = screen.getAllByRole("columnheader");
    const cells = within(bodyRows()[0] as HTMLElement).getAllByRole("cell");
    expect(headers.map(tier)).toEqual(expected);
    expect(cells.map(tier)).toEqual(expected);
  });

  it("sits in a wrapper that scrolls sideways", async () => {
    serve([trade(1)], 5);
    renderTable();

    const table = await screen.findByRole("table");

    expect(table.parentElement?.classList.contains("overflow-x-auto")).toBe(true);
  });

  it.each([
    ["en", "PnL %"],
    ["es", "PnL %"],
  ])("reads the heading Return as PnL %% in %s", async (language, heading) => {
    await i18n.changeLanguage(language);
    serve([trade(1)], 5);
    renderTable();

    await screen.findByRole("table");

    const headers = headerNames();
    expect(headers).toContain(heading);
    expect(headers).not.toContain("Return");
    expect(headers).not.toContain("Rendimiento");
  });

  it("shows the stored figures of a row: entry, exit, size, fees and PnL", async () => {
    serve(
      [
        trade(1, {
          entry_price: "0.451200000000000000",
          exit_price: "0.463100000000000000",
          size: "1250.000000000000000000",
          fees: "0.63",
          pnl: "14.25",
        }),
      ],
      5,
    );
    renderTable();

    await screen.findByRole("table");

    const cells = within(bodyRows()[0] as HTMLElement).getAllByRole("cell");
    expect(cells.slice(4, 9).map((cell) => cell.textContent)).toEqual(["0.4512", "0.4631", "1250", "0.63", "+14.25"]);
  });

  it("shows an em dash with its reason for a null entry, exit and size, and no cell shows 0", async () => {
    serve([trade(1, { base_currency: null, entry_price: null, exit_price: null, size: null })], 5);
    renderTable();

    await screen.findByRole("table");

    const cells = within(bodyRows()[0] as HTMLElement).getAllByRole("cell");
    const reason = i18n.t("strategies.performance.trades.notDerivable");
    for (const cell of cells.slice(4, 7)) {
      expect(cell.textContent ?? "").toContain("—");
      expect(within(cell).queryByText(reason)).toBeInTheDocument();
      expect(cell.textContent ?? "").not.toMatch(/\d/);
    }
  });

  it("writes a fee in another currency after the fees, as + 0.00012 BNB", async () => {
    serve([trade(1, { other_fees: [{ currency: "BNB", amount: "0.000120000000000000" }] }), trade(2)], 5);
    renderTable();

    await screen.findByRole("table");

    const [withOther, plain] = bodyRows() as [HTMLElement, HTMLElement];
    const feesWith = within(withOther).getAllByRole("cell")[7];
    expect(feesWith?.textContent ?? "").toContain("0.63");
    expect(feesWith ? within(feesWith).queryByText("+ 0.00012 BNB") : null).toBeInTheDocument();
    expect(within(plain).queryByText(/BNB/)).toBeNull();
  });

  // Was "keeps the incomplete-fees mark on the PnL cell": the mark is now an asterisk (owner decision 46),
  // so the words leave the cell and the hint text becomes its title and its screen-reader text.
  it("shows an asterisk right after the PnL figure of an incomplete-fee row, in ink-3, with the hint as title and screen-reader text, and not the words", async () => {
    serve([trade(1, { fees_complete: false })], 5);
    renderTable();

    await screen.findByRole("table");

    const hint = i18n.t("strategies.performance.trades.feesIncompleteHint");
    const pnlCell = within(bodyRows()[0] as HTMLElement).getAllByRole("cell")[8] as HTMLElement;
    const mark = within(pnlCell).queryByTitle(hint);
    expect(mark).toBeInTheDocument();
    expect(mark?.classList.contains("text-ink-3")).toBe(true);
    expect(mark?.textContent ?? "").toContain("*");
    expect(within(pnlCell).queryByText(hint)).toBeInTheDocument();
    expect(pnlCell.textContent ?? "").toMatch(/^\+1\.50\*/);
    expect(pnlCell.textContent ?? "").not.toContain(i18n.t("strategies.performance.trades.feesIncomplete"));
  });

  it("says a figure that is not a number is unreadable instead of drawing it", async () => {
    serve([trade(1, { entry_price: "1e3", exit_price: "x", size: "NaN", fees: "" })], 5);
    renderTable();

    await screen.findByRole("table");

    const cells = within(bodyRows()[0] as HTMLElement).getAllByRole("cell");
    const unreadable = i18n.t("strategies.performance.trades.cellUnreadable");
    expect([cells[4], cells[5], cells[6], cells[7]].map((cell) => cell?.textContent)).toEqual([
      unreadable,
      unreadable,
      unreadable,
      unreadable,
    ]);
  });

  it("shows PnL % and Pool capital at open empty for a row with no recorded capital", async () => {
    serve([trade(1, { capital_at_open: null, return: null })], 5);
    renderTable();

    await screen.findByRole("table");

    const cells = within(bodyRows()[0] as HTMLElement).getAllByRole("cell");
    expect(cells[9]?.textContent ?? "").toContain("—");
    expect(cells[10]?.textContent ?? "").toContain("—");
    expect(cells[9]?.textContent ?? "").not.toContain("0.0%");
    expect(cells[8]?.textContent ?? "").toContain("+1.50");
  });

  // Edited for owner decision 46: the instants are the compact two-line form; the rest of the row is as before.
  it("writes the instants in UTC, the venue's pair spelling, the side and the signed figures", async () => {
    serve(
      [
        trade(1, {
          pair: "STXUSDT",
          direction: "SHORT",
          opened_at: "2026-09-29T23:30:00Z",
          closed_at: "2026-09-30T00:15:00.000001Z",
          pnl: "-3.25",
          return: "-0.0032500000",
          capital_at_open: "1000.00",
        }),
      ],
      5,
    );
    renderTable();

    await screen.findByRole("table");

    // Opened and Closed are two lines each (owner decision 46): the numeric date, then the 24-hour time.
    const cells = within(bodyRows()[0] as HTMLElement)
      .getAllByRole("cell")
      .map((cell, index) => (index < 2 ? Array.from(cell.children).map((line) => line.textContent).join(" ") : cell.textContent));
    expect(cells).toEqual([
      "9/29/2026 23:30",
      "9/30/2026 00:15",
      "STXUSDT",
      // The side in words, as the open positions write it (L32).
      "Short",
      "0.4512",
      "0.4631",
      "1250",
      "0.63",
      "-3.25",
      "-0.3%",
      "1,000.00",
      "Details",
    ]);
  });

  it("writes a coin-margined pool's figures in its own currency with eight decimals", async () => {
    serve([trade(1, { pnl: "0.00120000", capital_at_open: "0.05000000", return: "0.0240000000" })], 5);
    renderTable("BTC");

    await screen.findByRole("table");

    expect(screen.getByRole("columnheader", { name: "PnL BTC" })).toBeInTheDocument();
    const cells = within(bodyRows()[0] as HTMLElement).getAllByRole("cell");
    expect(cells[8]).toHaveTextContent("+0.00120000");
    expect(cells[10]).toHaveTextContent("0.05000000");
  });

  it("shows an em dash, never a zero, for a trade with no capital at open and no return", async () => {
    serve([trade(1, { capital_at_open: null, return: null })], 5);
    renderTable();

    await screen.findByRole("table");

    const cells = within(bodyRows()[0] as HTMLElement).getAllByRole("cell");
    expect(cells[9]).toHaveTextContent("—");
    expect(cells[10]).toHaveTextContent("—");
    expect(cells[9]).not.toHaveTextContent("0.0%");
    expect(cells[10]).not.toHaveTextContent("0.00");
    expect(cells[8]).toHaveTextContent("+1.50");
  });

  // Was "marks a trade whose fees are incomplete and no other", which looked for the words: the mark is an
  // asterisk now (owner decision 46), found by its title.
  it("marks a trade whose fees are incomplete with an asterisk and no other", async () => {
    serve([trade(1, { fees_complete: false }), trade(2)], 5);
    renderTable();

    await screen.findByRole("table");

    const hint = i18n.t("strategies.performance.trades.feesIncompleteHint");
    const [flagged, clean] = bodyRows() as [HTMLElement, HTMLElement];
    expect(within(flagged).queryByTitle(hint)).toBeInTheDocument();
    expect(within(clean).queryByTitle(hint)).toBeNull();
  });

  it("says a cell cannot be read, instead of drawing a number, and keeps the other rows", async () => {
    serve([trade(1, { pnl: "1e3", return: "x", capital_at_open: "NaN" }), trade(2)], 5);
    renderTable();

    await screen.findByRole("table");

    const cells = within(bodyRows()[0] as HTMLElement).getAllByRole("cell");
    const unreadable = i18n.t("strategies.performance.trades.cellUnreadable");
    expect(cells[8]).toHaveTextContent(unreadable);
    expect(cells[9]).toHaveTextContent(unreadable);
    expect(cells[10]).toHaveTextContent(unreadable);
    expect(within(bodyRows()[1] as HTMLElement).getAllByRole("cell")[8]).toHaveTextContent("+2.50");
  });

  it("keeps a raw instant it cannot read rather than throw", async () => {
    serve([trade(1, { opened_at: "not a date" })], 5);
    renderTable();

    await screen.findByRole("table");

    expect(within(bodyRows()[0] as HTMLElement).getAllByRole("cell")[0]).toHaveTextContent("not a date");
  });

  it("is titled and labelled in Spanish", async () => {
    await i18n.changeLanguage("es");
    serve([trade(1, { direction: "SHORT" })], 5);
    renderTable();

    await screen.findByRole("table");

    expect(screen.getByRole("heading", { name: "Operaciones cerradas" })).toBeInTheDocument();
    expect(headerNames()).toEqual([
      "Apertura (UTC)",
      "Cierre (UTC)",
      "Par",
      "Sentido",
      "Entrada",
      "Salida",
      "Tamaño",
      "Comisiones USDT",
      "PnL USDT",
      "PnL %",
      "Pool al abrir",
      "Detalle",
    ]);
    expect(screen.getByRole("button", { name: "Anterior" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
    expect(screen.getByText("Página 1")).toBeInTheDocument();
    expect(within(bodyRows()[0] as HTMLElement).getAllByRole("cell")[3]?.textContent).toBe("Corto");
  });
});

// The rehearsal mark (decision 43): a dry-run operation keeps its stored numbers. How it was filled is a dot
// beside the pair in the dry-run badge's amber, named by its tag and told in a tooltip, as the open positions
// mark their origin (L31); a real operation has the live dot.
describe("TradesTable rehearsal rows", () => {
  const rehearsal = (n: number, fillPrice: string, overrides: Partial<StrategyTrade> = {}) =>
    trade(n, { rehearsal: true, rehearsal_fill_price: fillPrice, ...overrides });
  const pairCell = (row: HTMLElement) => within(row).getAllByRole("cell")[2] as HTMLElement;
  const markOf = (row: HTMLElement) => within(pairCell(row)).getByRole("img");

  it("marks each rehearsal_fill_price value with a dot named by its own tag, beside the pair (L31)", async () => {
    serve([rehearsal(1, "FIXED_ONE"), rehearsal(2, "ALERT"), rehearsal(3, "UNDETERMINED")], 5);
    renderTable();

    await screen.findByRole("table");

    const rows = bodyRows() as [HTMLElement, HTMLElement, HTMLElement];
    expect(rows.map((row) => markOf(row).getAttribute("aria-label"))).toEqual([
      "Dry run · fixed price",
      "Dry run · alert price",
      "Dry run",
    ]);
    // The tag is no longer written under the pair: the cell reads the pair alone, on one line.
    expect(rows.map((row) => pairCell(row).textContent)).toEqual(["SOLUSDT", "SOLUSDT", "SOLUSDT"]);
    for (const row of rows) expect(markOf(row).querySelector("[data-dot]")).toHaveClass("bg-decision", "rounded-full");
  });

  it("names the dots in Spanish", async () => {
    await i18n.changeLanguage("es");
    serve([rehearsal(1, "FIXED_ONE"), rehearsal(2, "ALERT"), rehearsal(3, "UNDETERMINED")], 5);
    renderTable();

    await screen.findByRole("table");

    expect((bodyRows() as HTMLElement[]).map((row) => markOf(row).getAttribute("aria-label"))).toEqual([
      "Simulación · precio fijo",
      "Simulación · precio de la alerta",
      "Simulación",
    ]);
  });

  it("reads a value the panel does not know as the plain tag", async () => {
    serve([rehearsal(1, "SLIPPED")], 5);
    renderTable();

    await screen.findByRole("table");

    const row = bodyRows()[0] as HTMLElement;
    expect(markOf(row)).toHaveAttribute("aria-label", "Dry run");
    expect(within(row).queryByText("SLIPPED")).toBeNull();
  });

  it("gives a real row the live dot and no dry-run tag (L31)", async () => {
    serve([trade(1)], 5);
    renderTable();

    await screen.findByRole("table");

    const row = bodyRows()[0] as HTMLElement;
    expect(markOf(row)).toHaveAttribute("aria-label", "Live");
    expect(markOf(row).querySelector("[data-dot]")).toHaveClass("bg-gain");
    expect(within(row).queryByText(/Dry run/)).toBeNull();
  });

  it("tells the tag in a tooltip on hover, so the mark does not rest on colour alone (L31)", async () => {
    serve([rehearsal(1, "ALERT")], 5);
    renderTable();

    await screen.findByRole("table");

    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.mouseEnter(markOf(bodyRows()[0] as HTMLElement).parentElement as HTMLElement);
    expect(screen.getByRole("tooltip")).toHaveTextContent(/^Dry run · alert price$/);
  });

  // Fees are written like the PnL beside them (owner decision 46): a fee of 0 reads 0.00 in a USDT pool.
  it("prints entry 1, exit 1 and fees 0.00 on a fixed-price row, and no cell is blank", async () => {
    serve(
      [
        rehearsal(1, "FIXED_ONE", {
          entry_price: "1.000000000000000000",
          exit_price: "1.000000000000000000",
          fees: "0",
        }),
      ],
      5,
    );
    renderTable();

    await screen.findByRole("table");

    const cells = within(bodyRows()[0] as HTMLElement).getAllByRole("cell");
    expect([cells[4], cells[5], cells[7]].map((cell) => cell?.textContent)).toEqual(["1", "1", "0.00"]);
    expect(cells.map((cell) => (cell.textContent ?? "").trim() === "")).not.toContain(true);
  });

  it("draws a rehearsal row's PnL and PnL % in neutral ink and a real row's in the gain and loss colours", async () => {
    serve(
      [
        rehearsal(1, "FIXED_ONE", { pnl: "4.00", return: "0.0040000000" }),
        rehearsal(2, "ALERT", { pnl: "-3.25", return: "-0.0032500000" }),
        trade(3, { pnl: "4.00", return: "0.0040000000" }),
        trade(4, { pnl: "-3.25", return: "-0.0032500000" }),
      ],
      5,
    );
    renderTable();

    await screen.findByRole("table");

    const inks = bodyRows().map((row) => {
      const cells = within(row).getAllByRole("cell");
      return [cells[8], cells[9]].map((cell) =>
        cell?.classList.contains("text-gain") ? "gain" : cell?.classList.contains("text-loss") ? "loss" : "neutral",
      );
    });
    expect(inks).toEqual([
      ["neutral", "neutral"],
      ["neutral", "neutral"],
      ["gain", "gain"],
      ["loss", "loss"],
    ]);
  });
});

// The sentences below the table (task 9p.5.12; they sat under its title until owner decision 46,
// task 9p.5.32, moved them): each is true of a row of the page on
// screen, never of a page visited before. The texts are the spec's, with the owner's wording of
// 2026-10-05 in the ALERT one.
const NOTE = {
  en: [
    'Operations marked "Dry run" were filled by the simulated exchange, not at the venue. They are not counted in any figure on this page.',
    'A row marked "fixed price" was opened at a fixed price of 1, whatever the market price was. Its prices and its PnL are not a result.',
    'A row marked "alert price" was opened at the price its alert carried. It was sized at 1x and its fee is simulated at the taker rate, so its PnL is not what it would have made live.',
  ],
  es: [
    'Las operaciones marcadas "Simulación" fueron ejecutadas por el exchange simulado, no en el exchange real. No se cuentan en ninguna cifra de esta página.',
    'Una fila marcada "precio fijo" se abrió a un precio fijo de 1, cualquiera fuera el precio de mercado. Sus precios y su PnL no son un resultado.',
    'Una fila marcada "precio de la alerta" se abrió al precio que traía su alerta. Se dimensionó a 1x y su comisión es simulada a la tasa taker, así que su PnL no es el que habría dado en real.',
  ],
} as const;

describe("TradesTable sentences below the table", () => {
  const rehearsal = (n: number, fillPrice: string) =>
    trade(n, { rehearsal: true, rehearsal_fill_price: fillPrice });
  // The sentences wait behind the (i) beside the title: open it, when it is drawn, before looking for them.
  const shown = (language: "en" | "es" = "en") => {
    const button = screen.queryByRole("button", { name: language === "en" ? "About these trades" : "Sobre estas operaciones" });
    if (button?.getAttribute("aria-expanded") === "false") fireEvent.click(button);
    return NOTE[language].map((sentence) => screen.queryByText(sentence) !== null);
  };

  it.each([
    ["no rehearsal row", [trade(1)], [false, false, false]],
    ["a FIXED_ONE row", [rehearsal(1, "FIXED_ONE")], [true, true, false]],
    ["an ALERT row", [rehearsal(1, "ALERT")], [true, false, true]],
    ["an UNDETERMINED row", [rehearsal(1, "UNDETERMINED")], [true, false, false]],
    ["a value the panel does not know", [rehearsal(1, "SLIPPED")], [true, false, false]],
    ["a real row beside a FIXED_ONE and an ALERT row", [trade(1), rehearsal(2, "FIXED_ONE"), rehearsal(3, "ALERT")], [true, true, true]],
  ])("shows each sentence only when a row of the page makes it true: %s", async (_name, rows, expected) => {
    serve(rows, 5);
    renderTable();

    await screen.findByRole("table");

    expect(shown()).toEqual(expected);
  });

  it("follows the page on screen and never the pages visited before", async () => {
    serve([rehearsal(1, "FIXED_ONE"), trade(2), trade(3)], 1);
    renderTable();
    await screen.findByRole("table");
    expect(shown()).toEqual([true, true, false]);

    fireEvent.click(next());
    await screen.findByText(pageLabel(2));

    expect(shown()).toEqual([false, false, false]);

    fireEvent.click(previous());

    expect(shown()).toEqual([true, true, false]);
  });

  it("writes the sentences in Spanish, with the exact texts of the spec", async () => {
    await i18n.changeLanguage("es");
    serve([rehearsal(1, "FIXED_ONE"), rehearsal(2, "ALERT")], 5);
    renderTable();

    await screen.findByRole("table");

    expect(shown("es")).toEqual([true, true, true]);
  });

  it("keeps the section title Closed trades", async () => {
    serve([rehearsal(1, "ALERT")], 5);
    renderTable();

    await screen.findByRole("table");

    expect(screen.queryByRole("heading", { name: "Closed trades" })).toBeInTheDocument();
  });
});

// What decision 43 changes in the paging and the failure paths (task 9p.5.14): the request always
// opts in to rehearsal rows, and a page that lacks the new fields is refused whole.
describe("TradesTable under decision 43", () => {
  const withoutField = (row: StrategyTrade, field: keyof StrategyTrade) => {
    const copy: Record<string, unknown> = { ...row };
    delete copy[field];
    return copy;
  };
  const oldNineFields = (n: number) => {
    const row = trade(n);
    return {
      allocation_id: row.allocation_id,
      pair: row.pair,
      direction: row.direction,
      opened_at: row.opened_at,
      closed_at: row.closed_at,
      pnl: row.pnl,
      capital_at_open: row.capital_at_open,
      return: row.return,
      fees_complete: row.fees_complete,
    };
  };
  const refused = async () => {
    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.performance.trades.error"));
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryAllByRole("row")).toHaveLength(0);
  };

  it("carries include_rehearsal=true on every request, the first page and the page after Next", async () => {
    const server = serve([1, 2, 3].map((n) => trade(n)), 2);
    renderTable();
    await screen.findByRole("table");

    fireEvent.click(next());
    await screen.findByText(pageLabel(2));

    expect(server.requests).toHaveLength(2);
    expect(server.requests.map((request) => request.searchParams.get("include_rehearsal"))).toEqual(["true", "true"]);
  });

  it("refuses a page whose row lacks fees, whole, with the error state and Try again and no row", async () => {
    serve([], 5, () =>
      Promise.resolve(jsonResponse({ trades: [trade(1), withoutField(trade(2), "fees")], next_cursor: null, total: 1 })),
    );
    renderTable();

    await refused();
    expect(screen.queryByRole("button", { name: i18n.t("strategies.performance.trades.retry") })).toBeInTheDocument();
  });

  it("shows the error state and no invented figure for the nine-field rows of an older API", async () => {
    serve([], 5, () => Promise.resolve(jsonResponse({ trades: [oldNineFields(1)], next_cursor: null, total: 1 })));
    renderTable();

    await refused();
    expect(screen.queryByText("+1.50")).toBeNull();
    expect(screen.queryByText("0")).toBeNull();
  });

  it("loads the page on Try again once the API serves the new fields", async () => {
    let upgraded = false;
    serve([], 5, () =>
      Promise.resolve(
        jsonResponse({ trades: upgraded ? [trade(1)] : [oldNineFields(1)], next_cursor: null, total: 1 }),
      ),
    );
    renderTable();
    await refused();

    upgraded = true;
    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.performance.trades.retry") }));

    await screen.findByRole("table");
    expect(bodyRows()).toHaveLength(1);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("refuses the page of a rehearsal row whose rehearsal_fill_price is null", async () => {
    serve([], 5, () =>
      Promise.resolve(
        jsonResponse({ trades: [trade(1, { rehearsal: true, rehearsal_fill_price: null })], next_cursor: null, total: 1 }),
      ),
    );
    renderTable();

    await refused();
  });
});

// Opening an operation (task 9p.5.19): the Details control of a row opens the detail dialog for that
// operation alone; the fills are asked for only by the dialog being mounted.
describe("TradesTable opening an operation", () => {
  interface OperationsServer {
    fillsRequests: string[];
  }

  const fillsBody = (allocation: string) => ({
    allocation_id: allocation,
    fills: [
      { filled_at: "2026-09-30T10:00:00Z", side: "BUY", price: "0.451200000000000000", quantity: "1250.000000000000000000", fee: "0.310000000000000000", fee_currency: "USDT", rehearsal: false },
    ],
    truncated: false,
  });

  /** Serves one page with every row and the fills route; `fills` answers a fills request. */
  function serveOperations(
    rows: readonly StrategyTrade[],
    fills: (allocation: string) => Promise<Response> = (allocation) => Promise.resolve(jsonResponse(fillsBody(allocation))),
  ): OperationsServer {
    const fillsRequests: string[] = [];
    stubApi(HEALTH, [], undefined, {}, (url) => {
      const parsed = new URL(url, "http://localhost");
      const asked = /\/performance\/strategies\/[^/]+\/trades\/([^/]+)\/fills$/.exec(parsed.pathname);
      if (asked !== null) {
        fillsRequests.push(asked[1] as string);
        return fills(asked[1] as string);
      }
      if (/\/performance\/strategies\/[^/]+\/trades$/.test(parsed.pathname)) {
        return Promise.resolve(jsonResponse({ trades: [...rows], next_cursor: null, total: 1 }));
      }
      return undefined;
    });
    return { fillsRequests };
  }

  const detailsButtons = () => screen.queryAllByRole("button", { name: /^Details of/ });
  const dialogs = () => screen.queryAllByRole("dialog");
  const waitFor = (check: () => void) => vi.waitFor(check);
  /** A text inside the open dialog, or null when no dialog is open: a query that never throws. */
  const inDialog = (text: string) => {
    const dialog = screen.queryByRole("dialog");
    return dialog === null ? null : within(dialog).queryByText(text);
  };

  it("makes no fills request until an operation is opened, and one when it is", async () => {
    const server = serveOperations([trade(1), trade(2)]);
    renderTable();
    await screen.findByRole("table");

    expect(server.fillsRequests).toEqual([]);

    fireEvent.click(detailsButtons()[0] as HTMLElement);

    expect(screen.queryByRole("dialog")).toBeInTheDocument();
    await waitFor(() => expect(server.fillsRequests).toEqual([trade(1).allocation_id]));
  });

  it("shows the loading line and then the fills", async () => {
    let release: (response: Response) => void = () => undefined;
    serveOperations([trade(1)], () => new Promise<Response>((resolve) => (release = resolve)));
    renderTable();
    await screen.findByRole("table");

    fireEvent.click(detailsButtons()[0] as HTMLElement);

    expect(screen.queryByText("Loading the fills…")).toBeInTheDocument();
    release(jsonResponse(fillsBody(trade(1).allocation_id)));
    await waitFor(() => expect(screen.queryByRole("table", { name: "Fills" })).toBeInTheDocument());
    expect(screen.queryByText("Loading the fills…")).toBeNull();
  });

  it("keeps the figures on screen when the fills read fails", async () => {
    serveOperations([trade(1)], () => Promise.resolve(jsonResponse({ detail: "no such operation" }, 404)));
    renderTable();
    await screen.findByRole("table");

    fireEvent.click(detailsButtons()[0] as HTMLElement);

    await waitFor(() => expect(screen.queryByText("The fills could not be loaded.")).toBeInTheDocument());
    const dialog = screen.queryByRole("dialog") as HTMLElement;
    expect(within(dialog).queryByText("Entry price")).toBeInTheDocument();
    expect(within(dialog).queryByText("SOLUSDT · LONG")).toBeInTheDocument();
  });

  it("puts the fills table inside the dialog's own scrolling body", async () => {
    serveOperations([trade(1)]);
    renderTable();
    await screen.findByRole("table");

    fireEvent.click(detailsButtons()[0] as HTMLElement);

    await waitFor(() => expect(screen.queryByRole("table", { name: "Fills" })).toBeInTheDocument());
    const dialog = screen.queryByRole("dialog") as HTMLElement;
    const fills = screen.getByRole("table", { name: "Fills" });
    const scroller = fills.closest(".overflow-y-auto");
    expect(scroller).toBeInTheDocument();
    expect(dialog).toContainElement(scroller as HTMLElement);
  });

  it("has only one dialog open at a time", async () => {
    serveOperations([trade(1, { pair: "SOLUSDT" }), trade(2, { pair: "ETHUSDT" })]);
    renderTable();
    await screen.findByRole("table");

    fireEvent.click(detailsButtons()[0] as HTMLElement);
    expect(inDialog("SOLUSDT · LONG")).toBeInTheDocument();
    fireEvent.click(detailsButtons()[1] as HTMLElement);

    expect(dialogs()).toHaveLength(1);
    expect(inDialog("ETHUSDT · LONG")).toBeInTheDocument();
    expect(screen.queryByText("SOLUSDT · LONG")).toBeNull();
  });

  it.each([
    ["Escape", () => fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" })],
    ["Close", () => fireEvent.click(screen.getByRole("button", { name: "Close" }))],
  ])("returns focus to the Details button on %s", async (_name, close) => {
    serveOperations([trade(1), trade(2)]);
    renderTable();
    await screen.findByRole("table");
    const opener = detailsButtons()[1] as HTMLElement;
    opener.focus();
    fireEvent.click(opener);
    expect(screen.queryByRole("dialog")).toBeInTheDocument();

    close();

    expect(dialogs()).toHaveLength(0);
    expect(document.activeElement).toBe(opener);
  });

  it.each([
    ["Enter", pressEnter],
    ["Space", pressSpace],
  ])("reaches the Details controls with Tab and opens one with %s", async (_name, press) => {
    serveOperations([trade(1), trade(2)]);
    renderTable();
    await screen.findByRole("table");

    // The headings are words and take no stop; each row's dot does (its tip opens on focus, L31), then its Details.
    const stops = [pressTab(), pressTab(), pressTab(), pressTab()];

    expect(stops[0]).toContainElement(within(bodyRows()[0] as HTMLElement).getByRole("img", { name: "Live" }));
    expect(stops[1]).toBe(detailsButtons()[0]);
    expect(stops[3]).toBe(detailsButtons()[1]);
    press();
    expect(inDialog("SOLUSDT · LONG")).toBeInTheDocument();
  });

  it("gives twenty Details controls twenty distinct accessible names", async () => {
    serveOperations(Array.from({ length: 20 }, (_, index) => trade(index + 1)));
    renderTable();
    await screen.findByRole("table");

    const names = detailsButtons().map((button) => button.getAttribute("aria-label"));

    expect(names).toHaveLength(20);
    expect(new Set(names).size).toBe(20);
    expect(names[0]).toBe("Details of SOLUSDT LONG, closed Sep 29, 2026, 12:30");
  });
});

// Every panel string is localized (task 9p.5.23): the table, a rehearsal row's dialog and its fills
// table read Spanish from i18n, the side of an operation stays LONG and SHORT, and no key of
// strategies.performance.trades exists in one language only.
describe("TradesTable localization", () => {
  /** Every leaf of a locale object as `path -> string`. */
  const flatten = (node: unknown, prefix = ""): Record<string, string> =>
    typeof node === "string"
      ? { [prefix]: node }
      : Object.entries(node as Record<string, unknown>).reduce<Record<string, string>>(
          (all, [key, child]) => ({ ...all, ...flatten(child, prefix === "" ? key : `${prefix}.${key}`) }),
          {},
        );

  const visibleTexts = (): string[] => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const texts: string[] = [];
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
      const value = (node.textContent ?? "").trim();
      if (value !== "") texts.push(value);
    }
    return texts;
  };

  it("has every strategies.performance.trades key in both languages", () => {
    const english = Object.keys(flatten(en.strategies.performance.trades)).sort();
    const spanish = Object.keys(flatten(es.strategies.performance.trades)).sort();

    expect(spanish).toEqual(english);
  });

  it("reads Spanish from i18n in the table, a rehearsal row's dialog and its fills table, the side in words in the table (L32)", async () => {
    await i18n.changeLanguage("es");
    const row = trade(1, { rehearsal: true, rehearsal_fill_price: "ALERT", direction: "SHORT", other_fees: [{ currency: "BNB", amount: "0.00012" }] });
    stubApi(HEALTH, [], undefined, {}, (url) => {
      const path = new URL(url, "http://localhost").pathname;
      if (/\/trades\/[^/]+\/fills$/.test(path)) {
        const fill = {
          filled_at: "2026-09-30T10:00:00Z",
          side: "BUY",
          price: "1.000000000000000000",
          quantity: "2.000000000000000000",
          fee: "0",
          fee_currency: "USDT",
          rehearsal: true,
        };
        return Promise.resolve(
          jsonResponse({
            allocation_id: row.allocation_id,
            fills: [fill, { ...fill, side: "SELL", rehearsal: false }],
            truncated: true,
          }),
        );
      }
      if (/\/trades$/.test(path)) return Promise.resolve(jsonResponse({ trades: [row], next_cursor: null, total: 1 }));
      return undefined;
    });
    renderTable();
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: /^Detalle de/ }));
    await vi.waitFor(() => expect(screen.queryByRole("table", { name: "Ejecuciones" })).toBeInTheDocument());

    // Every English text of this section's keys that differs in Spanish, and has no placeholder.
    const english = flatten(en.strategies.performance.trades);
    const spanish = flatten(es.strategies.performance.trades);
    const onlyEnglish = new Set(
      Object.entries(english)
        .filter(([key, value]) => spanish[key] !== value && !value.includes("{{"))
        .map(([, value]) => value),
    );
    const texts = visibleTexts();

    expect(texts.filter((text) => onlyEnglish.has(text))).toEqual([]);
    expect(texts).toEqual(expect.arrayContaining([
        "Compra",
        "Venta",
        "Ejecuciones",
        "Hora (UTC)",
        "Lado",
        "Precio",
        "Comisión",
        "Simulación · precio de la alerta",
        "Cerrar",
      ]));
    // The table writes the side in words, as the open positions do (L32); the dialog's title keeps LONG and SHORT.
    expect(texts).toContain("Corto");
    expect(screen.getByRole("dialog")).toHaveTextContent("SHORT");
    expect(texts).not.toContain("Sell");
    expect(texts).not.toContain("Buy");
  });
});

// The incomplete-fees sentence (task 9p.5.27) is the PnL column's tip now (owner ask, 2026-11-09): told
// when a row of the page on screen makes it true, never for a page visited before. The tip starts with
// the column's note under its name in words (L30); the dry-run sentences are pinned by "TradesTable sentences
// below the table". With no row making it true, the column has no tip at all.
describe("TradesTable incomplete-fees tip", () => {
  const TIP_EN = "A fee paid in a third currency is not in this PnL.";
  const TIP_ES = "Una comisión pagada en una tercera moneda no está en este PnL.";
  const pnlTip = () => {
    const name = within(screen.getByRole("table")).getByText("PnL USDT");
    fireEvent.mouseEnter(name);
    const tip = screen.queryByRole("tooltip")?.textContent ?? null;
    fireEvent.mouseLeave(name);
    return tip;
  };

  it.each([
    ["no row with incomplete fees", [trade(1), trade(2)], null],
    ["a row with incomplete fees", [trade(1), trade(2, { fees_complete: false })], TIP_EN],
  ])("tells it only when a row of the page makes it true: %s", async (_name, rows, expected) => {
    serve(rows, 5);
    renderTable();

    await screen.findByRole("table");

    expect(pnlTip()).toBe(expected);
  });

  it("follows the page on screen and never the pages visited before", async () => {
    serve([trade(1, { fees_complete: false }), trade(2), trade(3)], 1);
    renderTable();
    await screen.findByRole("table");
    expect(pnlTip()).toBe(TIP_EN);

    fireEvent.click(next());
    await screen.findByText(pageLabel(2));

    expect(pnlTip()).toBeNull();

    fireEvent.click(previous());

    expect(pnlTip()).toBe(TIP_EN);
  });

  it("is a paragraph nowhere, with the dry-run sentences or without them", async () => {
    serve([trade(1, { rehearsal: true, rehearsal_fill_price: "ALERT", fees_complete: false })], 5);
    renderTable();

    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "About these trades" }));

    expect(screen.queryByText(/A fee paid in a third currency/, { selector: "p" })).toBeNull();
    expect(screen.queryByText(NOTE.en[2])).toBeInTheDocument();
  });

  it("is written in Spanish", async () => {
    await i18n.changeLanguage("es");
    serve([trade(1, { fees_complete: false })], 5);
    renderTable();

    await screen.findByRole("table");

    expect(pnlTip()).toBe(TIP_ES);
  });
});

// Opened and Closed are compact (task 9p.5.29, owner decision 46): the numeric date in the panel's
// language and the 24-hour time in ink-3, both in UTC, on one line as the prototype's table writes them (L30).
describe("TradesTable compact instants", () => {
  const lines = (cell: HTMLElement | undefined) => Array.from(cell?.children ?? []).map((line) => line.textContent);

  it.each([
    ["en", ["10/5/2026", "01:30"], ["10/6/2026", "23:45"]],
    ["es", ["5/10/2026", "01:30"], ["6/10/2026", "23:45"]],
  ])("writes the date and the time of Opened and Closed in %s, in UTC", async (language, opened, closed) => {
    await i18n.changeLanguage(language);
    serve([trade(1, { opened_at: "2026-10-05T01:30:00Z", closed_at: "2026-10-06T23:45:00.000001Z" })], 5);
    renderTable();

    await screen.findByRole("table");

    const cells = within(bodyRows()[0] as HTMLElement).getAllByRole("cell");
    expect(lines(cells[0])).toEqual(opened);
    expect(lines(cells[1])).toEqual(closed);
  });

  it("draws the time beside the date on the same line, in ink-3 (L30)", async () => {
    serve([trade(1, { opened_at: "2026-10-05T01:30:00Z" })], 5);
    renderTable();

    await screen.findByRole("table");

    const cell = within(bodyRows()[0] as HTMLElement).getAllByRole("cell")[0] as HTMLElement;
    const time = within(cell).queryByText("01:30");
    expect(time).toBeInTheDocument();
    expect(time?.classList.contains("block")).toBe(false);
    expect(time?.classList.contains("text-ink-3")).toBe(true);
    expect(cell).toHaveClass("whitespace-nowrap");
    expect(within(cell).queryByText("10/5/2026")?.classList.contains("text-ink-3")).toBe(false);
  });
});

// The shorter figures of the table (task 9p.5.30, owner decision 46): Entry, Exit and Size by tableFigureText,
// Fees like the PnL beside them, a fee in another currency by figureText.
describe("TradesTable shorter figures", () => {
  const figureCells = async (row: StrategyTrade, currency = "USDT") => {
    serve([row], 5);
    renderTable(currency);
    await screen.findByRole("table");
    return within(bodyRows()[0] as HTMLElement).getAllByRole("cell");
  };

  it("writes Entry, Exit and Size with at most five decimals and a four-digit floor", async () => {
    const cells = await figureCells(
      trade(1, { entry_price: "0.705295610000000000", exit_price: "2515.952800000000000000", size: "0.000005120000000000" }),
    );

    expect([cells[4], cells[5], cells[6]].map((cell) => cell?.textContent)).toEqual(["0.7053", "2515.9528", "0.00000512"]);
  });

  it("writes Fees with the pool currency's decimals and no sign, like the PnL", async () => {
    const cells = await figureCells(trade(1, { fees: "0.630000000000000000" }));

    expect(cells[7]?.textContent).toBe("0.63");
  });

  it("writes a fee of 0 as 0.00 in a USDT pool", async () => {
    expect((await figureCells(trade(1, { fees: "0" })))[7]?.textContent).toBe("0.00");
  });

  it("writes the fees of a coin-margined pool with eight decimals", async () => {
    expect((await figureCells(trade(1, { fees: "0.00012" }), "BTC"))[7]?.textContent).toBe("0.00012000");
  });

  it("keeps a fee in another currency as written by figureText, never as zero", async () => {
    const cells = await figureCells(trade(1, { other_fees: [{ currency: "BNB", amount: "0.000120000000000000" }] }));

    expect(cells[7] ? within(cells[7]).queryByText("+ 0.00012 BNB") : null).toBeInTheDocument();
  });
});

// The columns are named in words in the prototype's compact boxed table (L30), and the notes wait behind one (i)
// beside the title (owner ask, 2026-11-09).
describe("TradesTable headings and the (i) beside the title", () => {
  const BUTTON = "About these trades";
  const FEES_HINT = "A fee paid in a third currency is not in this PnL.";

  it("is a card of its own with the boxed table of the open positions, its columns named in words (L30, L32)", async () => {
    serve([trade(1)], 5);
    renderTable();
    const table = await screen.findByRole("table", { name: "Closed trades" });

    const card = screen.getByRole("region", { name: "Closed trades" });
    expect(card).toContainElement(table);
    expect(card.closest('[data-testid="report-section"]')).toBeNull();
    expect(table.parentElement).toHaveClass("rounded-lg", "border", "border-rule");
    const headers = screen.getAllByRole("columnheader");
    expect(headers.map((header) => header.textContent)).toEqual([
      "Opened (UTC)",
      "Closed (UTC)",
      "Pair",
      "Side",
      "Entry",
      "Exit",
      "Size",
      "Fees USDT",
      "PnL USDT",
      "PnL %",
      "Pool at open",
      "Details",
    ]);
    for (const header of headers) {
      expect(header.querySelector("svg")).toBeNull();
      // The same size as the open positions and By pair (L32).
      expect(header).toHaveClass("bg-ground", "text-[12.5px]");
    }
    for (const cell of within(bodyRows()[0] as HTMLElement).getAllByRole("cell")) expect(cell).toHaveClass("text-[13px]", "px-3");
    // The prototype's small button (`.btn.sm`), 30 px high.
    expect(screen.getByRole("button", { name: /^Details of/ })).toHaveClass("h-[30px]");
  });

  it("draws no title over the Details column, as the open positions draw none over Close now, and right-aligns it (L31)", async () => {
    serve([trade(1)], 5);
    renderTable();
    await screen.findByRole("table");

    const head = screen.getAllByRole("columnheader").at(-1) as HTMLElement;
    expect(within(head).getByText("Details")).toHaveClass("sr-only");
    expect(head).toHaveClass("text-right");
    const cell = within(bodyRows()[0] as HTMLElement).getAllByRole("cell").at(-1) as HTMLElement;
    expect(cell).toContainElement(screen.getByRole("button", { name: /^Details of/ }));
    expect(cell).toHaveClass("text-right");
    expect(cell).not.toHaveClass("text-left");
  });

  it("keeps the dry-run sentences closed behind the (i) beside the title, in their order, until it is clicked", async () => {
    serve([trade(1, { rehearsal: true, rehearsal_fill_price: "ALERT" })], 5);
    renderTable();
    await screen.findByRole("table");

    const button = screen.getByRole("button", { name: BUTTON });
    const title = screen.getByRole("heading", { name: "Closed trades" });
    expect(title.parentElement).toContainElement(button);
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(NOTE.en[0])).toBeNull();

    fireEvent.click(button);

    const first = screen.getByText(NOTE.en[0]);
    const third = screen.getByText(NOTE.en[2]);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(first.compareDocumentPosition(third) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("table").compareDocumentPosition(first) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
  });

  it("draws no (i) when no row of the page is a dry run", async () => {
    serve([trade(1), trade(2)], 5);
    renderTable();
    await screen.findByRole("table");

    expect(screen.queryByRole("button", { name: BUTTON })).toBeNull();
  });

  it("says the incomplete fees in the PnL column's tip when a row makes it true, and in no paragraph", async () => {
    serve([trade(1, { fees_complete: false })], 5);
    renderTable();
    await screen.findByRole("table");

    expect(screen.queryByText(`* ${FEES_HINT}`)).toBeNull();
    expect(screen.queryByRole("button", { name: BUTTON })).toBeNull();
    fireEvent.mouseEnter(within(screen.getByRole("table")).getByText("PnL USDT"));
    expect(screen.getByRole("tooltip").textContent).toBe(FEES_HINT);
  });

  it("gives the PnL column no tip when every row has complete fees", async () => {
    serve([trade(1), trade(2)], 5);
    renderTable();
    await screen.findByRole("table");

    fireEvent.mouseEnter(within(screen.getByRole("table")).getByText("PnL USDT"));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});

// The count of operations at the card's top right, as the open positions count theirs (L32): every closed
// operation the table pages through, dry runs included, not the rows of the page on screen.
describe("TradesTable count of operations", () => {
  it("counts every operation the table lists, the same on every page", async () => {
    serve([trade(1), trade(2), trade(3), trade(4), trade(5), trade(6), trade(7)], 5);
    renderTable();

    await screen.findByRole("table");
    expect(screen.getByTestId("trades-count").textContent).toBe("7 trades");

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await vi.waitFor(() => expect(bodyRows()).toHaveLength(2));
    expect(screen.getByTestId("trades-count").textContent).toBe("7 trades");
  });

  it("is in the card's header, beside its title", async () => {
    serve([trade(1)], 5);
    renderTable();

    await screen.findByRole("table");
    const card = screen.getByRole("heading", { name: "Closed trades" }).closest("section") as HTMLElement;
    const header = screen.getByRole("heading", { name: "Closed trades" }).parentElement as HTMLElement;
    expect(within(card).getByTestId("trades-count")).toBeInTheDocument();
    expect(within(header.parentElement as HTMLElement).getByTestId("trades-count")).toBeInTheDocument();
  });

  it.each([
    [1, "1 operación"],
    [3, "3 operaciones"],
  ])("writes %i in Spanish as %s", async (count, text) => {
    await i18n.changeLanguage("es");
    serve(Array.from({ length: count }, (_, index) => trade(index + 1)), 5);
    renderTable();

    await screen.findByRole("table");
    expect(screen.getByTestId("trades-count").textContent).toBe(text);
  });

  it("is not drawn before a page has been read", () => {
    serve([], 5, () => new Promise<Response>(() => {}));
    renderTable();

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByTestId("trades-count")).toBeNull();
  });
});
