import { fireEvent, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TradesTable } from "@/features/strategies/TradesTable";
import type { StrategyTrade, StrategyTradesPage } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import { jsonResponse, lock, renderAt, stubApi, unlock } from "@/test/harness";

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
        : Promise.resolve(jsonResponse({ trades: all, next_cursor: null })),
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
    serve([], 5, () => Promise.resolve(jsonResponse({ trades: [{ ...trade(1), pnl: 4.2 }], next_cursor: null })));
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
  it("shows twelve columns in the order Opened, Closed, Pair, Side, Entry, Exit, Size, Fees USDT, PnL USDT, PnL %, Pool capital at open, Details", async () => {
    serve([trade(1)], 5);
    renderTable();

    await screen.findByRole("table");

    expect(screen.getAllByRole("columnheader").map((header) => header.textContent)).toEqual([
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
      "Pool capital at open",
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
      "xl:table-cell",
      "xl:table-cell",
      "always",
      "always",
      "xl:table-cell",
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

    const headers = screen.getAllByRole("columnheader").map((header) => header.textContent);
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

  it("keeps the incomplete-fees mark on the PnL cell", async () => {
    serve([trade(1, { fees_complete: false })], 5);
    renderTable();

    await screen.findByRole("table");

    const cells = within(bodyRows()[0] as HTMLElement).getAllByRole("cell");
    expect(cells[8]?.textContent ?? "").toContain(i18n.t("strategies.performance.trades.feesIncomplete"));
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

    const cells = within(bodyRows()[0] as HTMLElement)
      .getAllByRole("cell")
      .map((cell) => cell.textContent);
    expect(cells).toEqual([
      "Sep 29, 2026, 23:30",
      "Sep 30, 2026, 00:15",
      "STXUSDT",
      "SHORT",
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

  it("marks a trade whose fees are incomplete and no other", async () => {
    serve([trade(1, { fees_complete: false }), trade(2)], 5);
    renderTable();

    await screen.findByRole("table");

    const [flagged, clean] = bodyRows() as [HTMLElement, HTMLElement];
    expect(within(flagged).getByText(i18n.t("strategies.performance.trades.feesIncomplete"))).toBeInTheDocument();
    expect(within(clean).queryByText(i18n.t("strategies.performance.trades.feesIncomplete"))).toBeNull();
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
    expect(screen.getAllByRole("columnheader").map((header) => header.textContent)).toEqual([
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
      "Capital del pool al abrir",
      "Detalle",
    ]);
    expect(screen.getByRole("button", { name: "Anterior" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
    expect(screen.getByText("Página 1")).toBeInTheDocument();
    expect(within(bodyRows()[0] as HTMLElement).getAllByRole("cell")[3]).toHaveTextContent("SHORT");
  });
});

// The rehearsal mark (decision 43): a dry-run operation keeps its stored numbers, beside a text
// tag under the pair that says how it was filled, in the amber token of the dry-run badge.
describe("TradesTable rehearsal rows", () => {
  const rehearsal = (n: number, fillPrice: string, overrides: Partial<StrategyTrade> = {}) =>
    trade(n, { rehearsal: true, rehearsal_fill_price: fillPrice, ...overrides });
  const pairCell = (row: HTMLElement) => within(row).getAllByRole("cell")[2] as HTMLElement;

  it("shows each rehearsal_fill_price value's own tag on its own line under the pair", async () => {
    serve([rehearsal(1, "FIXED_ONE"), rehearsal(2, "ALERT"), rehearsal(3, "UNDETERMINED")], 5);
    renderTable();

    await screen.findByRole("table");

    const [fixed, alert, undetermined] = bodyRows() as [HTMLElement, HTMLElement, HTMLElement];
    const fixedTag = within(pairCell(fixed)).queryByText("Dry run · fixed price");
    const alertTag = within(pairCell(alert)).queryByText("Dry run · alert price");
    const plainTag = within(pairCell(undetermined)).queryByText("Dry run");
    expect(fixedTag).toBeInTheDocument();
    expect(alertTag).toBeInTheDocument();
    expect(plainTag).toBeInTheDocument();
    // Each tag is a block of its own inside the Pair cell, below the pair, and no row carries another's.
    for (const tag of [fixedTag, alertTag, plainTag]) {
      expect(tag?.classList.contains("block")).toBe(true);
      expect(tag?.parentElement).toBe(tag === fixedTag ? pairCell(fixed) : tag === alertTag ? pairCell(alert) : pairCell(undetermined));
    }
    expect(within(fixed).queryByText("Dry run · alert price")).toBeNull();
    expect(within(alert).queryByText("Dry run · fixed price")).toBeNull();
    expect(within(undetermined).queryByText(/·/)).toBeNull();
  });

  it("writes the tags in Spanish", async () => {
    await i18n.changeLanguage("es");
    serve([rehearsal(1, "FIXED_ONE"), rehearsal(2, "ALERT"), rehearsal(3, "UNDETERMINED")], 5);
    renderTable();

    await screen.findByRole("table");

    const [fixed, alert, undetermined] = bodyRows() as [HTMLElement, HTMLElement, HTMLElement];
    expect(within(pairCell(fixed)).queryByText("Simulación · precio fijo")).toBeInTheDocument();
    expect(within(pairCell(alert)).queryByText("Simulación · precio de la alerta")).toBeInTheDocument();
    expect(within(pairCell(undetermined)).queryByText("Simulación")).toBeInTheDocument();
  });

  it("reads a value the panel does not know as the plain tag", async () => {
    serve([rehearsal(1, "SLIPPED")], 5);
    renderTable();

    await screen.findByRole("table");

    const row = bodyRows()[0] as HTMLElement;
    expect(within(pairCell(row)).queryByText("Dry run")).toBeInTheDocument();
    expect(within(row).queryByText(/·/)).toBeNull();
    expect(within(row).queryByText("SLIPPED")).toBeNull();
  });

  it("leaves a real row unmarked", async () => {
    serve([trade(1)], 5);
    renderTable();

    await screen.findByRole("table");

    expect(within(bodyRows()[0] as HTMLElement).queryByText(/Dry run/)).toBeNull();
  });

  it("prints entry 1, exit 1 and fees 0 on a fixed-price row, and no cell is blank", async () => {
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
    expect([cells[4], cells[5], cells[7]].map((cell) => cell?.textContent)).toEqual(["1", "1", "0"]);
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

  it("writes the tag as text in the amber token of the dry-run badge, so it does not rest on colour alone", async () => {
    serve([rehearsal(1, "FIXED_ONE")], 5);
    renderTable();

    await screen.findByRole("table");

    const tag = within(pairCell(bodyRows()[0] as HTMLElement)).queryByText("Dry run · fixed price");
    expect(tag).toBeInTheDocument();
    expect(tag?.classList.contains("text-decision")).toBe(true);
    expect((tag?.textContent ?? "").length).toBeGreaterThan(0);
  });
});

// The sentences under the table's title (task 9p.5.12): each is true of a row of the page on
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

describe("TradesTable sentences under the title", () => {
  const rehearsal = (n: number, fillPrice: string) =>
    trade(n, { rehearsal: true, rehearsal_fill_price: fillPrice });
  const shown = (language: "en" | "es" = "en") => NOTE[language].map((sentence) => screen.queryByText(sentence) !== null);

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
      Promise.resolve(jsonResponse({ trades: [trade(1), withoutField(trade(2), "fees")], next_cursor: null })),
    );
    renderTable();

    await refused();
    expect(screen.queryByRole("button", { name: i18n.t("strategies.performance.trades.retry") })).toBeInTheDocument();
  });

  it("shows the error state and no invented figure for the nine-field rows of an older API", async () => {
    serve([], 5, () => Promise.resolve(jsonResponse({ trades: [oldNineFields(1)], next_cursor: null })));
    renderTable();

    await refused();
    expect(screen.queryByText("+1.50")).toBeNull();
    expect(screen.queryByText("0")).toBeNull();
  });

  it("loads the page on Try again once the API serves the new fields", async () => {
    let upgraded = false;
    serve([], 5, () =>
      Promise.resolve(
        jsonResponse({ trades: upgraded ? [trade(1)] : [oldNineFields(1)], next_cursor: null }),
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
        jsonResponse({ trades: [trade(1, { rehearsal: true, rehearsal_fill_price: null })], next_cursor: null }),
      ),
    );
    renderTable();

    await refused();
  });
});
