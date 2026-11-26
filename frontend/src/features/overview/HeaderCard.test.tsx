import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PoolPanel } from "@/features/overview/PoolPanel";
import type { OpenPool, OpenPosition } from "@/shared/api/positions";
import { useHiddenStore } from "@/shared/hidden/hidden-store";
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
 * RD.3, ex1 and ex2: one header card per pool, at the top of its section: the balance with the eye, the capital in
 * positions, the 30-day sparkline with its return, and four figures that are all time. Rule 7: a card is never merged
 * with another pool's.
 */

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const USDT_POOL: OpenPool = { exchange: "bybit", venue: "usdt-m", settlement_currency: "USDT" };
const KEY = "bybit/usdt-m/USDT";
const BALANCE = { total: "5000.00", available: "1284.52", observed_at: "2026-09-30T10:00:00+00:00", stale: false };
const POOL = { ...pool("bybit", "usdt-m", "USDT", BALANCE), reserved: "215.48" };

beforeEach(async () => {
  unlock();
  resetExchangeScope();
  setViewport("wide");
  useHiddenStore.setState({ hidden: false });
  await act(() => i18n.changeLanguage("en"));
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  useHiddenStore.setState({ hidden: false });
  await act(() => i18n.changeLanguage("en"));
});

async function settle() {
  for (let turn = 0; turn < 3; turn += 1) await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
}

/** Seven days of the curve ending today and a spread of ranges, each range with its own figures. */
function report(): PerformanceStub {
  const day = (offset: number) => new Date(Date.now() - offset * 86_400_000).toISOString().slice(0, 10);
  return {
    kind: "ok",
    body: {
      ...emptyPerformance("bybit", "usdt-m", "USDT"),
      trade_count: 8,
      total_pnl: "2414.30",
      max_drawdown: "-0.0870000000",
      ranges: [
        { range: "7D", pnl: "5.00", return: "0.0100000000", trade_count: 1 },
        { range: "30D", pnl: "41.20", return: "0.0420000000", trade_count: 3 },
        { range: "90D", pnl: "77.00", return: "0.0500000000", trade_count: 6 },
        { range: "1Y", pnl: "88.00", return: "0.0600000000", trade_count: 7 },
        { range: "All", pnl: "2414.30", return: "0.2414000000", trade_count: 8 },
      ],
      curve: [
        { date: day(20), daily_return: "0.0100000000", index: "1.0100000000", drawdown: "0" },
        { date: day(10), daily_return: "0.0200000000", index: "1.0302000000", drawdown: "0" },
        { date: day(2), daily_return: "0.0100000000", index: "1.0405000000", drawdown: "0" },
      ],
      monthly: [{ year: 2026, month: 9, return: "0.0302000000" }],
    },
  };
}

function positions(count: number): OpenPosition[] {
  return Array.from({ length: count }, (_, index) =>
    openPosition({
      pool: USDT_POOL,
      currency: "USDT",
      markets: [`PAIR${index}USDT`],
      strategy_name: `Strategy ${index}`,
      mark_price: "190",
      unrealized_pnl: "4.5",
    }),
  );
}

async function mountPanel(performance: PerformanceStub = report(), open = positions(3), poolRow = POOL, sole = false) {
  stubApi(HEALTH, [], { kind: "ok", body: [poolRow] }, { [KEY]: performance }, undefined, {}, undefined, {
    kind: "ok",
    body: openState(open),
  });
  renderAt(<PoolPanel pool={poolRow} sole={sole} />);
  await settle();
  return await screen.findByTestId("pool-panel");
}

describe("the header card", () => {
  it("names the balance, the pool and the capital in positions, in the pool's own currency", async () => {
    const panel = await mountPanel();

    const card = within(panel).getByTestId("header-card");
    expect(within(card).getByText("Available balance")).toBeInTheDocument();
    expect(within(card).getByTestId("pool-eyebrow")).toHaveTextContent("Bybit, usdt-m pool in USDT");
    expect(within(card).getByTestId("ledger-lead")).toHaveTextContent(/^1,284\.52USDT$/);
    expect(within(card).getByTestId("header-capital")).toHaveTextContent("Capital in positions");
    // The margin granted to the three real positions (3 x 30.00) and the 215.48 still reserved in flight (L36).
    expect(within(card).getByTestId("header-capital")).toHaveTextContent("305.48 USDT");
  });

  it("says a pool that is the exchange's only one is single", async () => {
    const panel = await mountPanel(report(), positions(3), POOL, true);

    expect(within(panel).getByTestId("pool-eyebrow")).toHaveTextContent("Bybit, single USDT pool");
  });

  it("draws the four figures of the whole history, whatever range the chart shows", async () => {
    const panel = await mountPanel();

    const stats = within(panel).getByTestId("ledger-line");
    expect(within(stats).getByText("Total PnL")).toBeInTheDocument();
    expect(within(stats).getByTestId("ledger-pnl")).toHaveTextContent("+2,414.30");
    expect(within(stats).getByTestId("ledger-pnl")).toHaveTextContent("USDT");
    expect(within(stats).getByTestId("ledger-return")).toHaveTextContent("+24.1%");
    expect(within(stats).getByTestId("ledger-deepest")).toHaveTextContent("-8.7%");
    expect(within(stats).getByTestId("ledger-open")).toHaveTextContent("3");

    fireEvent.click(within(panel).getByRole("radio", { name: "7D" }));

    expect(within(stats).getByTestId("ledger-pnl")).toHaveTextContent("+2,414.30");
    expect(within(stats).getByTestId("ledger-return")).toHaveTextContent("+24.1%");
  });

  it("draws the sparkline of the last 30 days with that range's return", async () => {
    const panel = await mountPanel();

    const spark = within(panel).getByTestId("header-spark");
    expect(within(spark).getByText("Return, last 30 days")).toBeInTheDocument();
    expect(within(spark).getByTestId("header-spark-return")).toHaveTextContent("+4.2%");
    expect(spark.querySelector("svg path.stroke-gain")?.getAttribute("d") ?? "").toMatch(/^M/);
  });

  it("keeps the (i) of a stale balance", async () => {
    const panel = await mountPanel(report(), positions(1), { ...POOL, balance: { ...BALANCE, stale: true } });

    fireEvent.click(within(within(panel).getByTestId("ledger-group-available")).getByRole("button", { name: "Balance out of date" }));
    expect(within(panel).getByTestId("balance-stale")).toHaveTextContent("Balance is out of date: last synced");
  });

  it("keeps the balance and the eye when the report is on its way, and none of the report's figures", async () => {
    const panel = await mountPanel({ kind: "pending" });

    expect(within(panel).getByTestId("ledger-lead")).toHaveTextContent("1,284.52");
    expect(within(panel).getByRole("button", { name: "Hide balances" })).toBeInTheDocument();
    expect(within(panel).getByText("Loading this pool's performance…")).toBeInTheDocument();
    expect(within(panel).queryByTestId("ledger-line")).not.toBeInTheDocument();
    expect(within(panel).queryByTestId("header-spark")).not.toBeInTheDocument();
  });

  it("is an em dash, not zero, for a balance nothing has synced", async () => {
    const panel = await mountPanel(report(), positions(1), { ...POOL, balance: null });

    expect(within(panel).getByTestId("ledger-lead")).toHaveTextContent("—");
  });
});

describe("the eye on the header card (S1)", () => {
  it("hides the balance, the capital and the PnL in currency, and keeps the percentages and the counts", async () => {
    const panel = await mountPanel();
    const card = within(panel).getByTestId("header-card");

    fireEvent.click(within(card).getByRole("button", { name: "Hide balances" }));

    expect(within(card).getByTestId("ledger-lead")).toHaveTextContent("******USDT");
    expect(within(card).getByTestId("header-capital")).toHaveTextContent("******");
    expect(within(card).getByTestId("ledger-pnl")).toHaveTextContent("******");
    expect(card.textContent).not.toContain("1,284.52");
    expect(card.textContent).not.toContain("305.48");
    expect(card.textContent).not.toContain("2,414.30");
    expect(within(card).getByTestId("ledger-return")).toHaveTextContent("+24.1%");
    expect(within(card).getByTestId("ledger-deepest")).toHaveTextContent("-8.7%");
    expect(within(card).getByTestId("ledger-open")).toHaveTextContent("3");
    expect(within(card).getByTestId("header-spark-return")).toHaveTextContent("+4.2%");
  });

  it("changes its own name, and the choice is the panel's: it reaches the open positions below", async () => {
    const panel = await mountPanel();
    const eye = within(panel).getByRole("button", { name: "Hide balances" });

    fireEvent.click(eye);

    expect(within(panel).getByRole("button", { name: "Show balances" })).toBe(eye);
    expect(useHiddenStore.getState().hidden).toBe(true);
    const table = within(panel).getByRole("table", { name: "Open positions" });
    expect(within(table).getAllByText("******").length).toBeGreaterThan(0);

    fireEvent.click(eye);

    expect(within(panel).getByRole("button", { name: "Hide balances" })).toBe(eye);
    expect(within(panel).getByTestId("ledger-lead")).toHaveTextContent("1,284.52");
  });

  it("keeps the chart's axes while hidden, since they are a percentage and dates", async () => {
    const panel = await mountPanel();
    expect(within(panel).getAllByTestId("y-label").length).toBeGreaterThan(0);

    fireEvent.click(within(panel).getByRole("button", { name: "Hide balances" }));

    expect(within(panel).getAllByTestId("y-label").length).toBeGreaterThan(0);
  });

  it("reads the stored choice when the page opens", async () => {
    useHiddenStore.setState({ hidden: true });
    const panel = await mountPanel();

    expect(within(panel).getByTestId("ledger-lead")).toHaveTextContent("******USDT");
    expect(within(panel).getByRole("button", { name: "Show balances" })).toBeInTheDocument();
  });

  it("names the eye in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    const panel = await mountPanel();

    fireEvent.click(within(panel).getByRole("button", { name: "Ocultar saldos" }));

    expect(within(panel).getByRole("button", { name: "Mostrar saldos" })).toBeInTheDocument();
    expect(within(panel).getByTestId("ledger-lead")).toHaveTextContent("******USDT");
  });
});

describe("the cards under the header card", () => {
  it("draws Open positions with its count, then Compounded return with the range selector as a segmented control, then Monthly performance (L36)", async () => {
    const panel = await mountPanel();

    const headings = within(panel).getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent);
    expect(headings).toEqual(["Open positions", "Compounded return", "Monthly performance"]);

    const chartCard = within(panel).getByRole("heading", { name: "Compounded return" }).closest("section") as HTMLElement;
    const ranges = within(chartCard).getByRole("radiogroup", { name: "Range" });
    expect(within(ranges).getAllByRole("radio").map((radio) => radio.textContent)).toEqual(["7D", "30D", "90D", "1Y", "All"]);
    expect(within(ranges).getByRole("radio", { name: "30D" })).toBeChecked();

    const positionsCard = within(panel).getByRole("heading", { name: "Open positions" }).closest("section") as HTMLElement;
    expect(within(positionsCard).getByTestId("positions-count")).toHaveTextContent("3 positions");
  });

  it("counts one position in the singular and none as zero", async () => {
    const one = await mountPanel(report(), positions(1));
    expect(within(one).getByTestId("positions-count")).toHaveTextContent(/^1 position$/);
  });

  it("moves the chart's range and nothing else of the card", async () => {
    const panel = await mountPanel();

    fireEvent.click(within(panel).getByRole("radio", { name: "7D" }));

    await waitFor(() => expect(within(panel).getByRole("radio", { name: "7D" })).toBeChecked());
    expect(within(panel).getByTestId("header-spark-return")).toHaveTextContent("+4.2%");
  });
});

// "Capital in positions" read only the reservations in flight, which settle as soon as the order fills, so a held
// position left it at 0.00 (L36). It is the margin granted to the pool's real positions, plus what is still in flight.
describe("the capital in positions (L36)", () => {
  const capital = async (open: OpenPositionsStub, poolRow = POOL) => {
    stubApi(HEALTH, [], { kind: "ok", body: [poolRow] }, { [KEY]: report() }, undefined, {}, undefined, open);
    renderAt(<PoolPanel pool={poolRow} />);
    await settle();
    const panel = await screen.findByTestId("pool-panel");
    return within(within(panel).getByTestId("header-card")).getByTestId("header-capital");
  };
  const held = (overrides: Partial<OpenPosition>) =>
    openPosition({ pool: USDT_POOL, currency: "USDT", markets: ["SOLUSDT"], ...overrides });
  const NOTHING_RESERVED = { ...POOL, reserved: "0" };

  it("adds the margin granted to every real position of the pool, a position of both origins included", async () => {
    const line = await capital(
      { kind: "ok", body: openState([held({ margin_granted: "369.83" }), held({ origin: "mixed", margin_granted: "20.17" })]) },
      NOTHING_RESERVED,
    );
    expect(line).toHaveTextContent("390.00 USDT");
  });

  it("leaves out a dry-run position, which holds no money of the balance above it", async () => {
    const line = await capital(
      { kind: "ok", body: openState([held({ margin_granted: "369.83" }), held({ origin: "rehearsal", margin_granted: "500.00" })]) },
      NOTHING_RESERVED,
    );
    expect(line).toHaveTextContent("369.83 USDT");
  });

  it("leaves out another pool's positions (rule 7)", async () => {
    const other: OpenPool = { exchange: "bybit", venue: "inverse", settlement_currency: "BTC" };
    const line = await capital(
      { kind: "ok", body: openState([held({ margin_granted: "369.83" }), held({ pool: other, currency: "BTC", margin_granted: "0.5" })]) },
      NOTHING_RESERVED,
    );
    expect(line).toHaveTextContent("369.83 USDT");
  });

  it("says 0.00 when nothing is held and nothing is in flight", async () => {
    const line = await capital({ kind: "ok", body: openState([]) }, NOTHING_RESERVED);
    expect(line).toHaveTextContent("0.00 USDT");
  });

  it("draws a dash, not a smaller sum, when a real position's margin cannot be read", async () => {
    const line = await capital(
      { kind: "ok", body: openState([held({ margin_granted: "369.83" }), held({ margin_granted: null })]) },
      NOTHING_RESERVED,
    );
    expect(line).toHaveTextContent("Capital in positions —");
    expect(line.textContent).not.toContain("369.83");
  });

  it("draws a dash while the positions cannot be read", async () => {
    const line = await capital({ kind: "status", status: 500, body: { detail: "boom" } });
    expect(line).toHaveTextContent("Capital in positions —");
    expect(line.textContent).not.toContain("215.48");
  });
});
