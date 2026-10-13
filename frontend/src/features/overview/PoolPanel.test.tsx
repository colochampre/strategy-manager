import { act, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OverviewPage } from "@/features/overview/OverviewPage";
import { PoolPanel } from "@/features/overview/PoolPanel";
import type { OpenPool, OpenPosition } from "@/shared/api/positions";
import i18n from "@/shared/i18n";
import {
  emptyPerformance,
  lock,
  openPosition,
  openState,
  pool,
  renderAt,
  resetExchangeScope,
  setViewport,
  stubApi,
  unlock,
} from "@/test/harness";
import type { OpenPositionsStub, PerformanceStub } from "@/test/harness";

/**
 * T13, the placement half (design addendum § H, the Overview part; § K rows 24 and 26): the list is drawn
 * outside the `report !== null` condition of `PoolPanel`, after the month grid and its summary.
 */

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const USDT_POOL: OpenPool = { exchange: "bybit", venue: "usdt-m", settlement_currency: "USDT" };
const BTC_POOL: OpenPool = { exchange: "bybit", venue: "inverse", settlement_currency: "BTC" };
const KEY = "bybit/usdt-m/USDT";
const BALANCE = { total: "5000.00", available: "1284.52", observed_at: "2026-09-30T10:00:00+00:00", stale: false };

beforeEach(async () => {
  unlock();
  resetExchangeScope();
  setViewport("wide");
  await act(() => i18n.changeLanguage("en"));
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

async function settle() {
  for (let turn = 0; turn < 3; turn += 1) await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
}

function held(pair: string, where: OpenPool = USDT_POOL, overrides: Partial<OpenPosition> = {}): OpenPosition {
  return openPosition({ pool: where, currency: where.settlement_currency, markets: [pair], strategy_name: `Strategy of ${pair}`, ...overrides });
}

const answering = (positions: OpenPosition[]): OpenPositionsStub => ({ kind: "ok", body: openState(positions) });

/** A report with one closed month, so that the grid and its summary are drawn. */
function report(overrides: Record<string, unknown> = {}): PerformanceStub {
  return {
    kind: "ok",
    body: { ...emptyPerformance("bybit", "usdt-m", "USDT"), monthly: [{ year: 2026, month: 9, return: "0.0302000000" }], ...overrides },
  };
}

const NO_REPORT: PerformanceStub = { kind: "status", status: 404, body: { detail: "no such pool" } };

async function mountPanel(positions: OpenPositionsStub, performance: PerformanceStub) {
  stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit", "usdt-m", "USDT", BALANCE)] }, { [KEY]: performance }, undefined, {}, undefined, positions);
  const view = renderAt(<PoolPanel pool={pool("bybit", "usdt-m", "USDT", BALANCE)} />);
  await settle();
  return view;
}

describe("a pool with a position and no report (T13; K row 24)", () => {
  it("draws its list and no count: the list does not depend on the report", async () => {
    await mountPanel(answering([held("AAVEUSDT")]), NO_REPORT);

    const panel = await screen.findByTestId("pool-panel");
    expect(await within(panel).findByText("No performance report exists for this pool yet.")).toBeInTheDocument();
    expect(within(panel).queryByRole("table", { name: "Open positions" })).toBeInTheDocument();
    expect(within(panel).queryByText("AAVEUSDT")).toBeInTheDocument();
    expect(within(panel).queryByTestId("monthly-summary")).not.toBeInTheDocument();
    expect(panel.textContent).not.toMatch(/\d+ open/);
  });

  it("draws its list too when the report failed, and the list's own states stay its own", async () => {
    await mountPanel(answering([held("AAVEUSDT")]), { kind: "status", status: 500, body: { detail: "boom" } });

    const panel = await screen.findByTestId("pool-panel");
    await waitFor(() => expect(within(panel).queryByText("This pool's performance could not be loaded.")).toBeInTheDocument());
    expect(within(panel).queryByRole("table", { name: "Open positions" })).toBeInTheDocument();
    expect(within(panel).queryByTestId("monthly-summary")).not.toBeInTheDocument();
  });

  it("draws its list while the report is still loading", async () => {
    await mountPanel(answering([held("AAVEUSDT")]), { kind: "pending" });

    const panel = await screen.findByTestId("pool-panel");
    expect(within(panel).queryByRole("table", { name: "Open positions" })).toBeInTheDocument();
  });
});

describe("a pool with a report (T13)", () => {
  it("draws the month grid, its summary and then the list, in that order", async () => {
    await mountPanel(answering([held("AAVEUSDT")]), report());

    const panel = await screen.findByTestId("pool-panel");
    const grid = within(panel).getByTestId("month-2026-9");
    const summary = within(panel).getByTestId("monthly-summary");
    const heading = within(panel).getByRole("heading", { name: "Open positions" });
    expect(grid.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(summary.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("draws the list under its own heading even when the pool holds nothing", async () => {
    await mountPanel(answering([]), report());

    const panel = await screen.findByTestId("pool-panel");
    expect(within(panel).queryByRole("heading", { name: "Open positions" })).toBeInTheDocument();
    expect(within(panel).queryByText("No open position.")).toBeInTheDocument();
  });
});

describe("the Overview asks for the open positions once (T22)", () => {
  it("shares one request between the panel's count and its list", async () => {
    const api = stubApi(
      HEALTH,
      [],
      { kind: "ok", body: [pool("bybit", "usdt-m", "USDT", BALANCE)] },
      { [KEY]: report() },
      undefined,
      {},
      undefined,
      answering([held("AAVEUSDT")]),
    );
    renderAt(<PoolPanel pool={pool("bybit", "usdt-m", "USDT", BALANCE)} />);
    await settle();

    expect(await screen.findByTestId("monthly-summary")).toHaveTextContent("1 open");
    expect(api.mock.calls.filter(([url]) => String(url).endsWith("/positions/open"))).toHaveLength(1);
    expect(api.unexpected).toEqual([]);
  });
});

describe("the count in the summary line (T13; spec 'The Overview's Count Says How Many Are Open And How Many Of Them Are Dry Run')", () => {
  const LEFT_OUT = { excluded: { ...emptyPerformance("bybit", "usdt-m", "USDT").excluded, open_trade_count: 4 } };

  async function summaryOf(positions: OpenPositionsStub, performance: PerformanceStub = report(LEFT_OUT)): Promise<string> {
    await mountPanel(positions, performance);
    const summary = await screen.findByTestId("monthly-summary");
    return summary.textContent ?? "";
  }

  it("counts every position of the pool, a position of both origins in the total and not among the dry run", async () => {
    const text = await summaryOf(
      answering([held("AAVEUSDT", USDT_POOL, { origin: "live" }), held("SFPUSDT", USDT_POOL, { origin: "rehearsal" }), held("STXUSDT", USDT_POOL, { origin: "mixed" })]),
    );

    expect(text).toContain("3 open, 1 of them dry run");
    expect(text).not.toContain("not in the curve");
  });

  it("writes 'N open' when no position is dry run", async () => {
    const text = await summaryOf(answering([held("AAVEUSDT"), held("STXUSDT")]));

    expect(text.endsWith("2 open")).toBe(true);
  });

  it("counts a dry-run position although the curve leaves nothing out", async () => {
    const text = await summaryOf(answering([held("SFPUSDT", USDT_POOL, { origin: "rehearsal" })]), report());

    expect(text).toContain("1 open, dry run");
  });

  it("writes no part about open positions when the pool holds none, whatever the curve leaves out", async () => {
    const text = await summaryOf(answering([]));

    expect(text).not.toContain("open");
  });

  it("counts the pool's own positions only: another pool's, even of the same exchange, are not in it (rule 7)", async () => {
    const text = await summaryOf(answering([held("AAVEUSDT"), held("BTCUSD", BTC_POOL), held("ETHUSDT", { ...USDT_POOL, settlement_currency: "USDC" })]));

    expect(text.endsWith("1 open")).toBe(true);
    expect(text).not.toContain("3 open");
    expect(text).not.toContain("2 open");
  });

  it("reads in Spanish, with the fixed Spanish of section I", async () => {
    await act(() => i18n.changeLanguage("es"));
    const text = await summaryOf(answering([held("AAVEUSDT"), held("SFPUSDT", USDT_POOL, { origin: "rehearsal" })]));

    expect(text).toContain("2 abiertas, 1 de ellas en simulación");
    expect(text).not.toContain("fuera de la curva");
  });

  it("writes no part about open positions while the read is loading", async () => {
    const text = await summaryOf({ kind: "pending" });

    expect(text).not.toContain("open");
  });

  it("writes no part about open positions when the read failed, old or new", async () => {
    const text = await summaryOf({ kind: "status", status: 500, body: { detail: "down" } });

    expect(text).not.toContain("open");
    expect(text).not.toContain("not in the curve");
  });
});

describe("a position in no panel's pool (T13; K row 26; owner decision Q7, 2026-10-13)", () => {
  it("is in no list: the Overview draws nothing for it and no line says so", async () => {
    stubApi(
      HEALTH,
      [],
      { kind: "ok", body: [pool("bybit", "usdt-m", "USDT", BALANCE)] },
      { [KEY]: report() },
      undefined,
      {},
      undefined,
      answering([held("AAVEUSDT"), held("BTCUSD", BTC_POOL, { strategy_name: "Stray strategy" })]),
    );
    renderAt(<OverviewPage />);
    await settle();

    const panel = await screen.findByTestId("pool-panel");
    expect(within(panel).queryByText("AAVEUSDT")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("BTCUSD");
    expect(document.body.textContent).not.toContain("Stray strategy");
    expect(document.body.textContent).not.toMatch(/no tab|no panel|not on this/i);
  });
});
