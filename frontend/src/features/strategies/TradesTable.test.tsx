import { fireEvent, screen, waitFor, within } from "@testing-library/react";
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
    if (!parsed.pathname.endsWith(`/performance/strategies/${ID}/trades`)) return undefined;
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
const loadMore = () => screen.getByRole("button", { name: i18n.t("strategies.performance.trades.loadMore") });

beforeEach(unlock);
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

describe("TradesTable", () => {
  it("test_infinite_query_keyset_cursor_loads_more_on_scroll_or_click", async () => {
    const all = [1, 2, 3, 4, 5].map((n) => trade(n));
    const server = serve(all, 2);
    renderTable();

    await screen.findByRole("table");
    expect(bodyRows()).toHaveLength(2);
    expect(server.requests).toHaveLength(1);

    fireEvent.click(loadMore());
    await waitFor(() => expect(bodyRows()).toHaveLength(4));
    fireEvent.click(loadMore());
    await waitFor(() => expect(bodyRows()).toHaveLength(5));

    // Every row once, in the order served: a wrong cursor would repeat or skip rows.
    expect(bodyRows().map((row) => within(row).getAllByRole("cell")[4]?.textContent)).toEqual([
      "+1.50",
      "+2.50",
      "+3.50",
      "+4.50",
      "+5.50",
    ]);
    // A null cursor ends the list.
    expect(screen.queryByRole("button", { name: i18n.t("strategies.performance.trades.loadMore") })).toBeNull();
    expect(server.requests).toHaveLength(3);
  });

  it("sends each next request the exact cursor the server answered, and never an offset", async () => {
    const all = [1, 2, 3, 4, 5].map((n) => trade(n));
    const server = serve(all, 2);
    renderTable();
    await screen.findByRole("table");

    fireEvent.click(loadMore());
    await waitFor(() => expect(bodyRows()).toHaveLength(4));
    fireEvent.click(loadMore());
    await waitFor(() => expect(bodyRows()).toHaveLength(5));

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

  it("shows no load-more button when the first page is the whole list", async () => {
    serve([trade(1), trade(2)], 5);
    renderTable();

    await screen.findByRole("table");

    expect(bodyRows()).toHaveLength(2);
    expect(screen.queryByRole("button", { name: i18n.t("strategies.performance.trades.loadMore") })).toBeNull();
  });

  it("disables the button and says it is loading while the next page is on its way", async () => {
    const all = [1, 2, 3].map((n) => trade(n));
    serve(all, 2);
    renderTable();
    await screen.findByRole("table");
    const fetchMock = vi.mocked(fetch);
    const realImplementation = fetchMock.getMockImplementation();
    fetchMock.mockImplementation((input, init) =>
      String(input).includes("before_allocation_id") ? new Promise<Response>(() => undefined) : (realImplementation?.(input, init) as Promise<Response>),
    );

    fireEvent.click(loadMore());

    const busy = await screen.findByRole("button", { name: i18n.t("strategies.performance.trades.loadingMore") });
    expect(busy).toBeDisabled();
    expect(bodyRows()).toHaveLength(2);
  });

  it("keeps the rows already loaded and says the next page failed, then loads it on a second click", async () => {
    const all = [1, 2, 3, 4].map((n) => trade(n));
    const server = serve(all, 2);
    renderTable();
    await screen.findByRole("table");
    server.failNextCursorRequest();

    fireEvent.click(loadMore());

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.performance.trades.nextFailed"));
    expect(bodyRows()).toHaveLength(2);

    fireEvent.click(loadMore());
    await waitFor(() => expect(bodyRows()).toHaveLength(4));
    expect(screen.queryByRole("alert")).toBeNull();
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
    expect(screen.queryByRole("button", { name: i18n.t("strategies.performance.trades.loadMore") })).toBeNull();
  });

  it("shows what the endpoint serves and no entry price, exit price, size or fees column (decision 43, pending)", async () => {
    serve([trade(1)], 5);
    renderTable();

    await screen.findByRole("table");

    expect(screen.getAllByRole("columnheader").map((header) => header.textContent)).toEqual([
      "Opened (UTC)",
      "Closed (UTC)",
      "Pair",
      "Side",
      "PnL USDT",
      "Return",
      "Pool capital at open",
    ]);
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
    expect(cells).toEqual(["Sep 29, 2026, 23:30", "Sep 30, 2026, 00:15", "STXUSDT", "SHORT", "-3.25", "-0.3%", "1,000.00"]);
  });

  it("writes a coin-margined pool's figures in its own currency with eight decimals", async () => {
    serve([trade(1, { pnl: "0.00120000", capital_at_open: "0.05000000", return: "0.0240000000" })], 5);
    renderTable("BTC");

    await screen.findByRole("table");

    expect(screen.getByRole("columnheader", { name: "PnL BTC" })).toBeInTheDocument();
    const cells = within(bodyRows()[0] as HTMLElement).getAllByRole("cell");
    expect(cells[4]).toHaveTextContent("+0.00120000");
    expect(cells[6]).toHaveTextContent("0.05000000");
  });

  it("shows an em dash, never a zero, for a trade with no capital at open and no return", async () => {
    serve([trade(1, { capital_at_open: null, return: null })], 5);
    renderTable();

    await screen.findByRole("table");

    const cells = within(bodyRows()[0] as HTMLElement).getAllByRole("cell");
    expect(cells[5]).toHaveTextContent("—");
    expect(cells[6]).toHaveTextContent("—");
    expect(cells[5]).not.toHaveTextContent("0.0%");
    expect(cells[6]).not.toHaveTextContent("0.00");
    expect(cells[4]).toHaveTextContent("+1.50");
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
    expect(cells[4]).toHaveTextContent(unreadable);
    expect(cells[5]).toHaveTextContent(unreadable);
    expect(cells[6]).toHaveTextContent(unreadable);
    expect(within(bodyRows()[1] as HTMLElement).getAllByRole("cell")[4]).toHaveTextContent("+2.50");
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
      "PnL USDT",
      "Rendimiento",
      "Capital del pool al abrir",
    ]);
    expect(within(bodyRows()[0] as HTMLElement).getAllByRole("cell")[3]).toHaveTextContent("Corto");
  });
});
