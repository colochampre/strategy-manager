import { act, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OpenMarks } from "@/features/positions/OpenMarks";
import { StrategyRow } from "@/features/strategies/StrategyRow";
import type { Strategy } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import { jsonResponse, lock, openOrder, openPosition, openState, renderAt, stubApi, unlock } from "@/test/harness";
import type { OpenPositionsStub } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;

const ALPHA = "11111111-1111-4111-8111-111111111111";
const BETA = "22222222-2222-4222-8222-222222222222";

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

function requests(api: ReturnType<typeof stubApi>): number {
  return api.mock.calls.filter(([url]) => String(url).endsWith("/positions/open")).length;
}

/** Lets the stubbed answers reach the components. */
async function settle() {
  for (let turn = 0; turn < 3; turn += 1) await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
}

/** The performance report a row asks for: an empty one, so the row's figures never fail. */
function rowRoutes(url: string) {
  if (/\/performance\/strategies\/[^/]+$/.test(url)) {
    return Promise.resolve(
      jsonResponse({
        pool: { exchange: "bybit", venue: "usdt-m", settlement_currency: "USDT" },
        currency: "USDT",
        day_boundary: "UTC",
        trade_count: 0,
        total_pnl: "0",
        max_drawdown: "0",
        excluded: {},
        ranges: [{ range: "All", pnl: "0", return: "0", trade_count: 0 }],
        curve: [],
        monthly: [],
        strategy_id: ALPHA,
        by_pair: [],
      }),
    );
  }
  return undefined;
}

async function mount(openPositions: OpenPositionsStub, row = strategy()) {
  const api = stubApi(HEALTH, [], undefined, {}, rowRoutes, {}, undefined, openPositions);
  const view = renderAt(<OpenMarks strategy={row} />);
  await settle();
  return { api, view };
}

const answering = (...args: Parameters<typeof openState>): OpenPositionsStub => ({ kind: "ok", body: openState(...args) });

function chips(): string[] {
  return screen.queryAllByRole("listitem").map((item) => item.textContent ?? "");
}

describe("a row's marks", () => {
  it("draws one chip per position and per order of that strategy", async () => {
    await mount(
      answering(
        [
          openPosition({ strategy_id: ALPHA, markets: ["AAVEUSDT"], side: "LONG", origin: "live" }),
          openPosition({ strategy_id: ALPHA, markets: ["SFPUSDT"], side: "SHORT", origin: "rehearsal" }),
        ],
        [openOrder({ strategy_id: ALPHA, market: "STXUSDT", origin: "rehearsal" })],
      ),
    );

    await waitFor(() => expect(chips()).toHaveLength(3));
    expect(chips()).toEqual([
      "AAVEUSDT · LONG · Live",
      "SFPUSDT · SHORT · Dry run",
      "STXUSDT · order in flight · Dry run",
    ]);
  });

  it("reads 'side not readable' where the side would be, and 'origin unknown' for an order with no id", async () => {
    await mount(
      answering(
        [openPosition({ strategy_id: ALPHA, markets: ["XYZBTC"], side: null, origin: "live", figures_missing: "UNRESOLVED_SYMBOL" })],
        [openOrder({ strategy_id: ALPHA, market: "SFPUSDT", origin: "unknown" })],
      ),
    );

    await waitFor(() => expect(chips()).toHaveLength(2));
    expect(chips()).toEqual(["XYZBTC · side not readable · Live", "SFPUSDT · order in flight · origin unknown"]);
  });

  it("joins the market keys of a position with several by ' / '", async () => {
    await mount(answering([openPosition({ strategy_id: ALPHA, markets: ["STXUSDT", "STXUSDC"] })]));

    await waitFor(() => expect(chips()).toEqual(["STXUSDT / STXUSDC · LONG · Live"]));
  });

  it("draws an order's chip dashed and a position's chip filled", async () => {
    await mount(answering([openPosition({ strategy_id: ALPHA })], [openOrder({ strategy_id: ALPHA })]));

    await waitFor(() => expect(chips()).toHaveLength(2));
    const [position, order] = screen.getAllByRole("listitem").map((item) => item.firstElementChild as HTMLElement);
    expect(position).toHaveClass("bg-panel-2");
    expect(position).not.toHaveClass("border-dashed");
    expect(order).toHaveClass("border-dashed");
  });

  it("keeps the chip of a disabled strategy: it does not read the switch", async () => {
    await mount(answering([openPosition({ strategy_id: ALPHA })]), strategy({ enabled: false }));

    await waitFor(() => expect(chips()).toHaveLength(1));
  });

  it("lets several chips wrap in their own row", async () => {
    await mount(
      answering(["AAVEUSDT", "LINKUSDT", "SUIUSDT"].map((market) => openPosition({ strategy_id: ALPHA, markets: [market] }))),
    );

    await waitFor(() => expect(chips()).toHaveLength(3));
    expect(screen.getByRole("list")).toHaveClass("flex-wrap");
  });

  it("names the list 'Open positions of {name}', in Spanish too", async () => {
    await mount(answering([openPosition({ strategy_id: ALPHA })]));
    await waitFor(() => expect(chips()).toHaveLength(1));
    expect(screen.getByRole("list", { name: "Open positions of Alpha" })).toBeInTheDocument();
  });

  it("names the list in Spanish through the same key", async () => {
    await act(() => i18n.changeLanguage("es"));
    await mount(answering([openPosition({ strategy_id: ALPHA })]));

    await waitFor(() => expect(chips()).toHaveLength(1));
    expect(screen.getByRole("list", { name: "Posiciones abiertas de Alpha" })).toBeInTheDocument();
    expect(chips()).toEqual(["SOLUSDT · LONG · En vivo"]);
  });

  it("takes the layout classes: its own grid row from lg, a full-width last line below it", async () => {
    await mount(answering([openPosition({ strategy_id: ALPHA })]));

    await waitFor(() => expect(chips()).toHaveLength(1));
    expect(screen.getByRole("list")).toHaveClass("basis-full", "lg:col-start-1", "lg:row-start-2");
  });
});

const ALLOCATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const DISCREPANCY = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";

function disagreeing() {
  return openPosition({
    allocation_id: ALLOCATION,
    strategy_id: ALPHA,
    markets: ["AAVEUSDT"],
    side: "LONG",
    venue_disagreement: {
      discrepancy_id: DISCREPANCY,
      venue_net_base: "0",
      ledger_net_base: "0.82",
      allocation_count: 1,
      last_observed_at: "2026-10-12T21:39:12Z",
    },
  });
}

function proposal(overrides: Record<string, unknown> = {}) {
  return {
    id: "pppppppp-pppp-4ppp-8ppp-pppppppppppp",
    discrepancy_id: DISCREPANCY,
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    symbol: "STXUSDT.P",
    kind: "ATTRIBUTABLE_FULL_CLOSE",
    allocation_id: ALLOCATION,
    strategy_id: ALPHA,
    side: "SELL",
    quantity: "0.82",
    observed_venue_net_base: "0",
    observed_ledger_net_base: "0.82",
    observed_allocation_ids: [ALLOCATION],
    fills: [],
    client_order_id: "vnu:bybit:order-1",
    expires_at: "2026-10-14T01:02:03+00:00",
    prepared_by_job_id: "55555555-5555-4555-8555-555555555555",
    created_at: "2026-10-13T01:02:03+00:00",
    state: "PENDING",
    decided_at: null,
    decided_by: null,
    decision_reason: null,
    execution_attempt_id: null,
    ...overrides,
  };
}

type BookingsAnswer = { kind: "ok"; body: unknown[] } | { kind: "pending" } | { kind: "status"; status: number };

/** Mounts the marks over one positions answer and one answer to the pending bookings. */
async function mountVenue(position: ReturnType<typeof disagreeing>, bookings: BookingsAnswer) {
  const route = (url: string) => {
    if (url.includes("/reconciliation/bookings")) {
      if (bookings.kind === "pending") return new Promise<Response>(() => undefined);
      if (bookings.kind === "status") return Promise.resolve(jsonResponse({ detail: "down" }, bookings.status));
      return Promise.resolve(jsonResponse(bookings.body));
    }
    return rowRoutes(url);
  };
  const api = stubApi(HEALTH, [], undefined, {}, route, {}, undefined, answering([position]));
  renderAt(<OpenMarks strategy={strategy()} />);
  await settle();
  await waitFor(() => expect(chips()).toHaveLength(1));
  return api;
}

const LINK = "See the pending decision";
const WORDS = "No booking is proposed for it.";

describe("the venue chip, with the link or the words (T19, the chip's half)", () => {
  it("follows its position's chip in the same item, with the red chip and its words", async () => {
    await mountVenue(disagreeing(), { kind: "ok", body: [] });

    await waitFor(() => expect(screen.queryByText("Venue disagrees")).toBeInTheDocument());
    const item = screen.getByRole("listitem");
    const [position, venue] = [...item.children];
    expect(position).toHaveTextContent("AAVEUSDT · LONG · Live");
    expect(venue).toHaveTextContent("Venue disagrees");
    expect(venue).toHaveClass("border-loss", "text-loss", "bg-transparent");
  });

  it("draws the link, named with the pair, when a pending proposal names this allocation and this discrepancy", async () => {
    await mountVenue(disagreeing(), { kind: "ok", body: [proposal()] });

    await waitFor(() => expect(screen.queryByRole("link", { name: `${LINK}, AAVEUSDT` })).toBeInTheDocument());
    const link = screen.getByRole("link", { name: `${LINK}, AAVEUSDT` });
    expect(link).toHaveTextContent(LINK);
    expect(link).toHaveAttribute("href", "/#decision-rail");
    expect(screen.queryByText(WORDS)).not.toBeInTheDocument();
  });

  it.each([
    ["no proposal is pending", []],
    ["the proposal names another discrepancy", [proposal({ discrepancy_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee" })]],
    ["the proposal names another allocation", [proposal({ allocation_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" })]],
    ["the proposal is not pending", [proposal({ state: "REJECTED" })]],
  ])("says that no booking is proposed, and links nowhere, when %s", async (_label, body) => {
    await mountVenue(disagreeing(), { kind: "ok", body });

    await waitFor(() => expect(screen.queryByText(WORDS)).toBeInTheDocument());
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText(WORDS)).toHaveClass("text-ink-2", "text-xs");
  });

  it("draws neither the link nor the words while the proposals load", async () => {
    await mountVenue(disagreeing(), { kind: "pending" });

    expect(screen.queryByText("Venue disagrees")).toBeInTheDocument();
    expect(screen.queryByText(WORDS)).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("draws neither when the read of the proposals failed", async () => {
    await mountVenue(disagreeing(), { kind: "status", status: 500 });

    expect(screen.queryByText("Venue disagrees")).toBeInTheDocument();
    expect(screen.queryByText(WORDS)).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});

describe("a row that has nothing to show", () => {
  it("draws no mark and no empty element when its strategy holds nothing", async () => {
    const { view } = await mount(answering([openPosition({ strategy_id: BETA })], [openOrder({ strategy_id: BETA })]));

    expect(chips()).toEqual([]);
    expect(view.container.firstElementChild).toBeNull();
  });

  it("draws nothing when the first read failed: the line above says why", async () => {
    const { view } = await mount({ kind: "status", status: 500, body: {} });

    expect(chips()).toEqual([]);
    expect(view.container.firstElementChild).toBeNull();
  });
});

describe("while the answer loads", () => {
  it("draws a decorative '…' with the translated text as its accessible name", async () => {
    const api = stubApi(HEALTH, [], undefined, {}, rowRoutes, {}, undefined, { kind: "pending" });
    renderAt(<OpenMarks strategy={strategy()} />);
    await settle();
    expect(requests(api)).toBe(1);

    const dots = screen.queryByText("…");
    expect(dots).toBeInTheDocument();
    expect(dots).toHaveAttribute("aria-hidden", "true");
    const name = screen.queryByText(en.positions.state.loading);
    expect(name).toBeInTheDocument();
    expect(name).toHaveClass("sr-only");
    expect(within(screen.getByRole("list")).getAllByRole("listitem")).toHaveLength(1);
  });
});

describe("in the row", () => {
  it("is the row's fourth child, after the name, the figures and the switch", async () => {
    const api = stubApi(HEALTH, [], undefined, {}, rowRoutes, {}, undefined, answering([openPosition({ strategy_id: ALPHA })]));
    renderAt(
      <ul>
        <StrategyRow strategy={strategy()} />
      </ul>,
    );
    await settle();
    expect(requests(api)).toBe(1);

    await waitFor(() => expect(screen.queryByRole("list", { name: "Open positions of Alpha" })).toBeInTheDocument());
    const row = screen.getByTestId("strategy-row");
    expect(row.children).toHaveLength(4);
    expect(row.children[3]).toBe(screen.getByRole("list", { name: "Open positions of Alpha" }));
  });
});
