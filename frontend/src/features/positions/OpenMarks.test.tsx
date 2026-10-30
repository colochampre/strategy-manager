import { act, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OpenMarks } from "@/features/positions/OpenMarks";
import { StrategyRow } from "@/features/strategies/StrategyRow";
import type { ConfirmedDiscrepancy } from "@/shared/api/discrepancies";
import type { Strategy } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import {
  confirmedBody,
  discrepancy,
  jsonResponse,
  lock,
  openOrder,
  openPosition,
  openState,
  renderAt,
  stubApi,
  unlock,
} from "@/test/harness";
import type { ConfirmedStub, OpenPositionsStub } from "@/test/harness";

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
    subscription: null,
    enabled: true,
    archived_at: null,
    allowed_pairs: ["SOLUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    visibility: "PRIVATE",
    secret_last4: "x4F2",
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

/** The discrepancy the position's disagreement names; its symbol is the TradingView spelling, the position's is the venue's (R21). */
function confirmedItem(overrides: Partial<ConfirmedDiscrepancy> = {}): ConfirmedDiscrepancy {
  return discrepancy({ discrepancy_id: DISCREPANCY, symbol: "AAVEUSDT.P", ...overrides });
}

const BEING_BOOKED: ConfirmedStub = {
  kind: "ok",
  body: confirmedBody({ being_booked: [confirmedItem({ reason: null })] }),
};

function needsOwner(overrides: Partial<ConfirmedDiscrepancy> = {}): ConfirmedStub {
  return { kind: "ok", body: confirmedBody({ needs_owner: [confirmedItem(overrides)] }) };
}

/** Mounts the marks over one positions answer and one answer to the confirmed discrepancies. */
async function mountVenue(position: ReturnType<typeof disagreeing>, confirmed: ConfirmedStub) {
  const api = stubApi(HEALTH, [], undefined, {}, rowRoutes, {}, undefined, answering([position]), confirmed);
  renderAt(<OpenMarks strategy={strategy()} />);
  await settle();
  await waitFor(() => expect(chips()).toHaveLength(1));
  return api;
}

const LINK = "See the discrepancy";
const ITEM_HREF = `/discrepancies#discrepancy-${DISCREPANCY}`;

describe("the venue chip, with the words and the link (T19, the chip's half; example 16a)", () => {
  it("follows its position's chip in the same item, with the red chip", async () => {
    await mountVenue(disagreeing(), BEING_BOOKED);

    await waitFor(() => expect(screen.queryByText("Venue disagrees")).toBeInTheDocument());
    const item = screen.getByRole("listitem");
    const [position, venue] = [...item.children];
    expect(position).toHaveTextContent("AAVEUSDT · LONG · Live");
    expect(venue).toHaveTextContent("Venue disagrees");
    expect(venue).toHaveClass("border-loss", "text-loss", "bg-transparent");
  });

  it("says 'being booked automatically' and draws the link to the item for an id in being_booked", async () => {
    await mountVenue(disagreeing(), BEING_BOOKED);

    await waitFor(() => expect(screen.queryByRole("link", { name: `${LINK}, AAVEUSDT` })).toBeInTheDocument());
    const link = screen.getByRole("link", { name: `${LINK}, AAVEUSDT` });
    expect(link).toHaveTextContent(LINK);
    expect(link).toHaveAttribute("href", ITEM_HREF);
    const words = screen.getByText(/being booked automatically/i);
    expect(words).toHaveClass("text-ink-2", "text-xs");
    expect(words).toContainElement(link);
    expect(screen.getByText("Venue disagrees")).toHaveClass("border-loss");
  });

  it.each([
    ["NOT_BOOKED", { reason: "NOT_BOOKED" as const, kind: "ATTRIBUTABLE_FULL_CLOSE" as const }, /could not be booked automatically/i],
    ["SEVERAL_ALLOCATIONS", { reason: "SEVERAL_ALLOCATIONS" as const, kind: "ATTRIBUTABLE_FULL_CLOSE" as const }, /one booking cannot split it/i],
    [
      "AMBIGUOUS_PARTIAL_REDUCE",
      { reason: "NOT_BOOKABLE" as const, kind: "AMBIGUOUS_PARTIAL_REDUCE" as const },
      /which strategy it reduced cannot be told/i,
    ],
  ])("says the words of a %s discrepancy in needs_owner, and links to the item", async (_name, overrides, words) => {
    await mountVenue(disagreeing(), needsOwner(overrides));

    await waitFor(() => expect(screen.queryByRole("link", { name: `${LINK}, AAVEUSDT` })).toBeInTheDocument());
    expect(screen.getByText(words)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: `${LINK}, AAVEUSDT` })).toHaveAttribute("href", ITEM_HREF);
    expect(screen.getByText("Venue disagrees")).toHaveClass("border-loss");
  });

  it("joins by the discrepancy's id: another id with the same pair makes no claim and draws no link", async () => {
    await mountVenue(disagreeing(), needsOwner({ discrepancy_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee" }));

    expect(screen.queryByText("Venue disagrees")).toBeInTheDocument();
    expect(screen.queryByText(/booked automatically/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it.each([
    ["the query loads", { kind: "pending" } as ConfirmedStub],
    ["the read failed", { kind: "status", status: 500, body: { detail: "down" } } as ConfirmedStub],
    ["the id is in neither list", { kind: "ok", body: confirmedBody() } as ConfirmedStub],
  ])("draws the red chip alone, with no words and no link, when %s", async (_label, confirmed) => {
    await mountVenue(disagreeing(), confirmed);

    expect(screen.queryByText("Venue disagrees")).toBeInTheDocument();
    expect(screen.getByRole("listitem")).toHaveTextContent("AAVEUSDT · LONG · LiveVenue disagrees");
    expect(screen.getByText("Venue disagrees")).toHaveClass("border-loss");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("asks for no booking proposal", async () => {
    const api = await mountVenue(disagreeing(), BEING_BOOKED);

    const urls = api.mock.calls.map(([url]) => String(url));
    expect(urls.filter((url) => url.includes("bookings"))).toEqual([]);
    expect(urls.filter((url) => url.endsWith("/reconciliation/confirmed"))).toHaveLength(1);
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
