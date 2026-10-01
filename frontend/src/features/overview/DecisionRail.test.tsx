import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { lock, pool, renderAt, resetExchangeScope, setViewport, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const POOLS = { kind: "ok", body: [pool("bybit", "linear"), pool("binance")] } as const;

function proposal(id: string, exchange: string, symbol: string) {
  return {
    id,
    discrepancy_id: "d",
    exchange,
    venue: "usdt-m",
    settlement_currency: "USDT",
    symbol,
    kind: "ATTRIBUTABLE_FULL_CLOSE",
    allocation_id: "a",
    strategy_id: "s",
    side: "SELL",
    quantity: "1",
    observed_venue_net_base: "0",
    observed_ledger_net_base: "-1",
    observed_allocation_ids: [],
    fills: [],
    client_order_id: "c",
    expires_at: "2026-09-24T01:02:03+00:00",
    prepared_by_job_id: "j",
    created_at: "2026-09-23T01:02:03+00:00",
    state: "PENDING",
    decided_at: null,
    decided_by: null,
    decision_reason: null,
    execution_attempt_id: null,
  };
}

const TWO_BYBIT_ONE_BINANCE = [
  proposal("p1", "bybit", "SOLUSDT.P"),
  proposal("p2", "bybit", "ETHUSDT.P"),
  proposal("p3", "binance", "XRPUSDT.P"),
];

/** True when `a` comes before `b` in the document. */
function before(a: Element, b: Element): boolean {
  return Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

describe("on a wide viewport", () => {
  it("test_pending_bookings_wide_viewport_right_rail", async () => {
    setViewport("wide");
    stubApi(HEALTH, TWO_BYBIT_ONE_BINANCE, POOLS);
    renderAt(<AppRoutes />, "/");

    const rail = await screen.findByRole("complementary");
    expect(await within(rail).findByText("SOLUSDT.P")).toBeInTheDocument();
    expect(within(rail).getByText("ETHUSDT.P")).toBeInTheDocument();
    expect(within(rail).queryByText("XRPUSDT.P")).not.toBeInTheDocument();

    const panel = await screen.findByTestId("pool-panel");
    expect(panel).not.toContainElement(rail);
    expect(rail).toHaveAttribute("data-placement", "right-rail");
    expect(before(panel, rail)).toBe(true);
    expect(screen.getAllByRole("complementary")).toHaveLength(1);
  });

  it("counts the selected exchange's proposals in amber, and only those", async () => {
    setViewport("wide");
    stubApi(HEALTH, TWO_BYBIT_ONE_BINANCE, POOLS);
    renderAt(<AppRoutes />, "/");

    const count = await screen.findByTestId("pending-count");
    expect(count).toHaveTextContent("2 pending");
    expect(count.className).toContain("text-decision");

    fireEvent.click(screen.getAllByRole("button", { name: "binance" })[0] as HTMLElement);
    await waitFor(() => expect(screen.getByTestId("pending-count")).toHaveTextContent("1 pending"));
  });

  it("explains what approving does while something is pending", async () => {
    setViewport("wide");
    stubApi(HEALTH, TWO_BYBIT_ONE_BINANCE, POOLS);
    renderAt(<AppRoutes />, "/");

    const rail = await screen.findByRole("complementary");
    expect(await within(rail).findByText(en.overview.decisionRail.explainer)).toBeInTheDocument();
  });
});

describe("on a narrow viewport", () => {
  it("test_pending_bookings_narrow_viewport_inflow_block_between_chart_and_grid", async () => {
    setViewport("narrow");
    stubApi(HEALTH, TWO_BYBIT_ONE_BINANCE, POOLS);
    renderAt(<AppRoutes />, "/");

    // The rail moves into the first panel once the panel exists; hold it only after that.
    const panel = await screen.findByTestId("pool-panel");
    const rail = await within(panel).findByRole("complementary");
    const chart = await within(panel).findByRole("img");
    const grid = await within(panel).findByRole("heading", { name: en.overview.monthlyGrid.title });
    const ledger = await within(panel).findByTestId("ledger-line");

    expect(panel).toContainElement(rail);
    expect(rail).toHaveAttribute("data-placement", "in-flow");
    expect(before(ledger, chart)).toBe(true);
    expect(before(chart, rail)).toBe(true);
    expect(before(rail, grid)).toBe(true);
    expect(screen.getAllByRole("complementary")).toHaveLength(1);
    expect(await within(rail).findByText("SOLUSDT.P")).toBeInTheDocument();
  });

  it("still shows the rail when the exchange has no pool panel to sit inside", async () => {
    setViewport("narrow");
    stubApi(HEALTH, TWO_BYBIT_ONE_BINANCE, { kind: "ok", body: [] });
    renderAt(<AppRoutes />, "/");

    const rail = await screen.findByRole("complementary");
    await waitFor(() => expect(rail).toHaveTextContent(en.overview.decisionRail.noExchanges));
    expect(screen.queryByTestId("pool-panel")).not.toBeInTheDocument();
  });
});

describe("with nothing pending", () => {
  it.each(["wide", "narrow"] as const)(
    "test_no_pending_bookings_shows_nothing_needs_your_decision_no_amber_count (%s)",
    async (width) => {
      setViewport(width);
      stubApi(HEALTH, [proposal("p3", "binance", "XRPUSDT.P")], POOLS);
      renderAt(<AppRoutes />, "/");

      await screen.findByTestId("pool-panel");
      const rail = await screen.findByRole("complementary");
      expect(await within(rail).findByText(en.overview.decisionRail.empty)).toBeInTheDocument();
      expect(screen.queryByTestId("pending-count")).not.toBeInTheDocument();
      expect(rail.querySelector(".text-decision")).toBeNull();
      expect(within(rail).queryByText(en.overview.decisionRail.explainer)).not.toBeInTheDocument();
      expect(within(rail).queryByText(/pending/)).not.toBeInTheDocument();
    },
  );

  it("shows no count while the bookings are still loading", async () => {
    setViewport("wide");
    const fetchMock = stubApi(HEALTH, [], POOLS);
    const original = fetchMock.getMockImplementation();
    fetchMock.mockImplementation((input, init) =>
      String(input).includes("/reconciliation/bookings")
        ? new Promise<Response>(() => undefined)
        : (original as NonNullable<typeof original>)(input, init),
    );
    renderAt(<AppRoutes />, "/");

    const rail = await screen.findByRole("complementary");
    expect(await within(rail).findByText(en.bookings.loading)).toBeInTheDocument();
    expect(screen.queryByTestId("pending-count")).not.toBeInTheDocument();
  });
});

describe("while the exchange scope is not known", () => {
  it.each([
    ["loading", { kind: "pending" }],
    ["failed with a 500", { kind: "status", status: 500, body: { detail: "boom" } }],
    ["failed with a network error", { kind: "network-error" }],
  ] as const)("asks for no bookings and shows no count when pools are %s", async (_label, pools) => {
    const fetchMock = stubApi(HEALTH, TWO_BYBIT_ONE_BINANCE, pools);
    renderAt(<AppRoutes />, "/");
    const rail = await screen.findByRole("complementary");
    await waitFor(() =>
      expect(rail).toHaveTextContent(/Loading exchanges|could not be loaded/),
    );
    await new Promise((resolve) => setTimeout(resolve, 50));

    const bookingCalls = fetchMock.mock.calls.filter((call) => String(call[0]).includes("/reconciliation/bookings"));
    expect(bookingCalls).toEqual([]);
    expect(screen.queryByTestId("pending-count")).not.toBeInTheDocument();
    expect(screen.queryByText("SOLUSDT.P")).not.toBeInTheDocument();
    expect(screen.queryByText("XRPUSDT.P")).not.toBeInTheDocument();
  });
});

describe("the booking actions", () => {
  it("opens the existing confirm dialog from the rail", async () => {
    setViewport("wide");
    stubApi(HEALTH, TWO_BYBIT_ONE_BINANCE, POOLS);
    renderAt(<AppRoutes />, "/");
    const rail = await screen.findByRole("complementary");

    const approve = await within(rail).findAllByRole("button", { name: en.bookings.actions.approve });
    fireEvent.click(approve[0] as HTMLElement);

    expect(await screen.findByText(en.bookings.dialogs.confirm.title)).toBeInTheDocument();
  });

  it("keeps every action at least 44 px tall", async () => {
    setViewport("wide");
    stubApi(HEALTH, TWO_BYBIT_ONE_BINANCE, POOLS);
    renderAt(<AppRoutes />, "/");
    const rail = await screen.findByRole("complementary");
    await within(rail).findByText("SOLUSDT.P");

    const buttons = [
      ...within(rail).getAllByRole("button", { name: en.bookings.actions.approve }),
      ...within(rail).getAllByRole("button", { name: en.bookings.actions.reject }),
    ];
    expect(buttons).toHaveLength(4);
    for (const button of buttons) expect(button.className).toContain("min-h-11");
  });
});

describe("copy", () => {
  it("has the rail's strings in English and Spanish", () => {
    for (const locale of [en, es]) {
      expect(locale.overview.decisionRail.explainer).toBeTruthy();
      expect(locale.overview.decisionRail.empty).toBeTruthy();
      expect(locale.overview.decisionRail.pending_one).toContain("{{count}}");
      expect(locale.overview.decisionRail.pending_other).toContain("{{count}}");
    }
  });
});
