import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import {
  emptyPerformance,
  heldSubscription,
  jsonResponse,
  openOrder,
  openPosition,
  openState,
  publicStrategy,
  renderAt,
  resetExchangeScope,
  setViewport,
  stubApi,
  unlock,
  unsyncedSharePreview,
} from "@/test/harness";

const STRATEGY_ID = "11111111-1111-4111-8111-111111111111";

interface Serve {
  held: () => Promise<Response>;
  publics?: () => Promise<Response>;
  /** The reader's open positions and orders; none unless a test says so. */
  open?: ReturnType<typeof openState>;
  /** The reader's own report in the strategy. */
  mine?: () => Promise<Response>;
}

/** The reader's own report in a strategy: 41.25 USDT made over all time. */
function myReport() {
  return {
    ...emptyPerformance("bybit", "usdt-m", "USDT"),
    strategy_id: STRATEGY_ID,
    by_pair: [],
    trade_count: 2,
    total_pnl: "41.25",
    ranges: ["7D", "30D", "90D", "1Y", "All"].map((range) => ({
      range,
      pnl: range === "All" ? "41.25" : "1.00",
      return: "0.02",
      trade_count: 2,
    })),
  };
}

function serve({ held, publics, open, mine }: Serve) {
  return stubApi(
    { kind: "ok", body: {} },
    [],
    { kind: "ok", body: [] },
    {},
    (url) => {
      if (url.endsWith("/api/subscriptions/held")) return held();
      if (url.endsWith("/api/public/strategies")) {
        return publics?.() ?? Promise.resolve(jsonResponse([publicStrategy({ id: STRATEGY_ID })]));
      }
      if (url.endsWith(`/performance/strategies/${STRATEGY_ID}`)) {
        return mine?.() ?? Promise.resolve(jsonResponse(myReport()));
      }
      if (url.includes(`/strategies/${STRATEGY_ID}/share-preview`)) {
        return Promise.resolve(jsonResponse(unsyncedSharePreview(STRATEGY_ID)));
      }
      return undefined;
    },
    {},
    undefined,
    open === undefined ? undefined : { kind: "ok", body: open },
  );
}

function open() {
  renderAt(<AppRoutes />, "/strategies");
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
  setViewport("wide");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the tabs of Strategies", () => {
  it("offers the three lists and marks the one on screen", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([])) });
    open();

    expect(await screen.findByRole("heading", { level: 1, name: i18n.t("strategies.title") })).toBeInTheDocument();
    const tabs = screen.getByRole("navigation", { name: i18n.t("strategies.tabs.label") });
    const links = within(tabs).getAllByRole("link");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      [i18n.t("strategies.tabs.subscriptions"), "/strategies"],
      [i18n.t("strategies.tabs.explore"), "/strategies/explore"],
      [i18n.t("strategies.tabs.authored"), "/strategies/authored"],
    ]);
    expect(links[0]).toHaveAttribute("aria-current", "page");
    expect(links[1]).not.toHaveAttribute("aria-current");
  });

  it("names the third list My strategies", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([])) });
    open();

    const tabs = await screen.findByRole("navigation", { name: i18n.t("strategies.tabs.label") });
    expect(within(tabs).getByRole("link", { name: "My strategies" })).toHaveAttribute("href", "/strategies/authored");
  });

  it("puts a decorative icon before the label of each list", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([])) });
    open();

    const tabs = await screen.findByRole("navigation", { name: i18n.t("strategies.tabs.label") });
    const links = within(tabs).getAllByRole("link");
    expect(links).toHaveLength(3);
    for (const link of links) {
      const icon = link.querySelector("svg");
      expect(icon).not.toBeNull();
      expect(icon).toHaveAttribute("aria-hidden", "true");
      expect(link.firstElementChild).toBe(icon);
    }
  });

  it("keeps My subscriptions unmarked on another list", async () => {
    stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) =>
      url.endsWith("/api/public/strategies") ? Promise.resolve(jsonResponse([])) : undefined,
    );
    renderAt(<AppRoutes />, "/strategies/explore");

    const tabs = await screen.findByRole("navigation", { name: i18n.t("strategies.tabs.label") });
    expect(within(tabs).getByRole("link", { name: i18n.t("strategies.tabs.subscriptions") })).not.toHaveAttribute(
      "aria-current",
    );
    expect(within(tabs).getByRole("link", { name: i18n.t("strategies.tabs.explore") })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});

describe("a card of My subscriptions shows what Explore shows", () => {
  it("names the strategy, its author on one line and its market on the next", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])) });
    open();

    const row = await screen.findByTestId("subscription-row");
    expect(within(row).getByRole("link", { name: "Alpha" })).toHaveAttribute("href", `/strategies/explore/${STRATEGY_ID}`);
    expect(within(row).getByTestId("subscription-origin")).toHaveTextContent(
      new RegExp(`^${i18n.t("strategies.subscriptions.by", { name: "Ana" })}$`),
    );
    expect(within(row).getByTestId("subscription-market")).toHaveTextContent(/^bybit · usdt-m · USDT$/);
  });

  it("draws the strategy's public figures: closed trades, return, deepest, win rate, subscribers and capital", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])) });
    open();

    const row = await screen.findByTestId("subscription-row");
    await waitFor(() => expect(within(row).getByTestId("subscription-trades")).toHaveTextContent(/^3$/));
    expect(within(row).getByTestId("subscription-return")).toHaveTextContent(/^\+12\.5\s?%$/);
    expect(within(row).getByTestId("subscription-deepest")).toHaveTextContent(/^[-−]5\.0\s?%$/);
    expect(within(row).getByTestId("subscription-winrate")).toHaveTextContent(/^60\s?%$/);
    expect(within(row).getByTestId("subscription-subscribers")).toHaveTextContent(/^2$/);
    expect(within(row).getByTestId("subscription-capital")).toHaveTextContent(/^1,500\.00 USDT$/);
    // The strategy's own age is not drawn: the card counts the reader's time in it instead.
    expect(within(row).queryByTestId("public-age")).not.toBeInTheDocument();
  });

  it("draws the reader's own PnL in the strategy, all time, left of the return, named as theirs (L.11)", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])) });
    open();

    const row = await screen.findByTestId("subscription-row");
    await waitFor(() => expect(within(row).getByTestId("subscription-pnl")).toHaveTextContent(/^\+41\.25 USDT$/));
    const order = Array.from(row.querySelectorAll("dd")).map((cell) => cell.getAttribute("data-testid"));
    expect(order.indexOf("subscription-pnl")).toBe(order.indexOf("subscription-return") - 1);
    const term = within(row).getByTestId("subscription-pnl").previousElementSibling as HTMLElement;
    expect(within(term).getByRole("img", { name: "Your PnL" })).toBeInTheDocument();
  });

  it("draws a dash for a PnL with no report of the reader's (L.11)", async () => {
    serve({
      held: () => Promise.resolve(jsonResponse([heldSubscription()])),
      mine: () => Promise.resolve(jsonResponse({ detail: "none" }, 404)),
    });
    open();
    const row = await screen.findByTestId("subscription-row");
    await waitFor(() => expect(within(row).getByTestId("subscription-pnl")).toHaveTextContent(/^—$/));
  });

  it("shows the dash, not a wait, in every public figure once the list has been read and holds nothing of it", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])), publics: () => Promise.resolve(jsonResponse([])) });
    open();

    const row = await screen.findByTestId("subscription-row");
    await waitFor(() => expect(within(row).getByTestId("subscription-trades")).toHaveTextContent(/^—$/));
    for (const key of ["return", "deepest", "winrate", "subscribers", "capital"]) {
      expect(within(row).getByTestId(`subscription-${key}`), key).toHaveTextContent(/^—$/);
    }
  });

  it("waits with an ellipsis while the public list is on its way, and claims nothing", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])), publics: () => new Promise<Response>(() => undefined) });
    open();

    const row = await screen.findByTestId("subscription-row");
    for (const key of ["trades", "return", "deepest", "winrate", "subscribers", "capital"]) {
      expect(within(row).getByTestId(`subscription-${key}`), key).toHaveTextContent(/^…$/);
    }
  });

  it("says whether the strategy runs, and for how long, from the seat itself", async () => {
    serve({
      held: () =>
        Promise.resolve(
          jsonResponse([
            heldSubscription({
              strategy_enabled: false,
              strategy_uptime: { seconds: 3 * 86_400, first_enabled_at: "2026-09-29T00:00:00Z", baseline: true },
            }),
          ]),
        ),
      publics: () => Promise.resolve(jsonResponse([])),
    });
    open();

    const row = await screen.findByTestId("subscription-row");
    expect(within(row).getByTestId("subscription-enabled")).toHaveAccessibleName(i18n.t("strategies.detail.disabled"));
    expect(within(row).getByTestId("subscription-uptime")).toHaveTextContent(/^≥3$/);
  });

  it("opens the strategy from anywhere on the card, through the one link", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])) });
    open();

    const row = await screen.findByTestId("subscription-row");
    expect(row).toHaveClass("relative");
    expect(within(row).getAllByRole("link")).toHaveLength(1);
    expect(within(row).getByRole("link", { name: "Alpha" })).toHaveClass("after:absolute", "after:inset-0");
  });

  it("counts the age from the day the reader subscribed, not from the strategy's creation", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-06T12:00:00Z"));
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription({ created_at: "2026-10-27T10:00:00Z" })])) });
    open();

    const age = await screen.findByTestId("subscription-age");
    expect(age).toHaveTextContent(/^10d$/);
    const figure = age.parentElement as HTMLElement;
    expect(within(figure).getByRole("img", { name: "Time subscribed" })).toBeInTheDocument();
  });

  it("adds the share of the pool and the leverage, each under its icon, the share in plain form", async () => {
    serve({
      held: () => Promise.resolve(jsonResponse([heldSubscription({ allocation_percent: "30.000000", leverage: 4 })])),
    });
    open();

    const share = await screen.findByTestId("subscription-share");
    expect(share).toHaveTextContent(/^30%$/);
    expect(
      within(share.parentElement as HTMLElement).getByRole("img", { name: "Share" }),
    ).toBeInTheDocument();
    const leverage = screen.getByTestId("subscription-leverage");
    expect(leverage).toHaveTextContent(/^x4$/);
    expect(
      within(leverage.parentElement as HTMLElement).getByRole("img", { name: "Leverage" }),
    ).toBeInTheDocument();
    // They come last, after the eight figures every card draws.
    const order = Array.from((await screen.findByTestId("subscription-row")).querySelectorAll("dd")).map((cell) =>
      cell.getAttribute("data-testid"),
    );
    expect(order.slice(-2)).toEqual(["subscription-share", "subscription-leverage"]);
  });

  it("offers no Leave, nor any other button: the seat is managed on the strategy's page", async () => {
    const fetchMock = serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])) });
    open();

    const row = await screen.findByTestId("subscription-row");
    await waitFor(() => expect(within(row).getByTestId("subscription-trades")).toHaveTextContent(/^3$/));
    expect(within(row).queryByRole("button")).not.toBeInTheDocument();
    expect(within(row).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(row).queryByRole("slider")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/share-preview"))).toBe(false);
  });

  it("draws only the reader's own figures for a strategy that is not on the public list", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])), publics: () => Promise.resolve(jsonResponse([])) });
    open();

    expect(await screen.findByTestId("subscription-share")).toBeInTheDocument();
    expect(screen.getByTestId("subscription-age")).toBeInTheDocument();
    expect(screen.getByTestId("subscription-uptime")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("subscription-trades")).toHaveTextContent(/^—$/));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says so when the public figures cannot be read, and still shows the reader's own", async () => {
    serve({
      held: () => Promise.resolve(jsonResponse([heldSubscription()])),
      publics: () => Promise.resolve(jsonResponse({ detail: "down" }, 500)),
    });
    open();

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.subscriptions.figuresError"));
    expect(screen.getByTestId("subscription-share")).toBeInTheDocument();
    expect(screen.getByTestId("subscription-trades")).toHaveTextContent(/^—$/);
  });

  it("says an author has no name yet, instead of a blank", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription({ author_name: null })])) });
    open();

    expect(await screen.findByTestId("subscription-origin")).toHaveTextContent(
      i18n.t("strategies.subscriptions.noAuthorName"),
    );
  });

  it("sends an author to their own page", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription({ authored: true, leverage: 2 })])) });
    open();

    const row = await screen.findByTestId("subscription-row");
    expect(within(row).getByRole("link", { name: "Alpha" })).toHaveAttribute("href", `/strategies/${STRATEGY_ID}`);
    expect(within(row).getByTestId("subscription-origin")).toHaveTextContent(i18n.t("strategies.subscriptions.yours"));
    expect(within(row).getByTestId("subscription-leverage")).toHaveTextContent(/^x2$/);
  });

  it("tells a leaving subscription apart", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription({ status: "LEAVING" })])) });
    open();

    const row = await screen.findByTestId("subscription-row");
    expect(within(row).getByText(i18n.t("strategies.subscriptions.leaving"))).toBeInTheDocument();
  });

  it("says nothing of leaving on a subscription that is not leaving", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])) });
    open();

    await screen.findByTestId("subscription-row");
    expect(screen.queryByText(i18n.t("strategies.subscriptions.leaving"))).not.toBeInTheDocument();
  });
});

describe("the reader's own open positions on a card (L.4)", () => {
  it("shows the positions and orders the reader's seat holds, as My strategies shows the author's", async () => {
    serve({
      held: () => Promise.resolve(jsonResponse([heldSubscription()])),
      open: openState(
        [openPosition({ strategy_id: STRATEGY_ID, markets: ["AAVEUSDT"], side: "LONG" })],
        [openOrder({ strategy_id: STRATEGY_ID, market: "SOLUSDT" })],
      ),
    });
    open();

    const row = await screen.findByTestId("subscription-row");
    const marks = await within(row).findByRole("list", { name: i18n.t("positions.marks.name", { name: "Alpha" }) });
    expect(within(marks).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "AAVEUSDT · LONG · Live",
      expect.stringContaining("SOLUSDT"),
    ]);
    expect(marks.parentElement).toHaveClass("relative", "z-10");
  });

  it("shows none of a position that belongs to another strategy", async () => {
    serve({
      held: () => Promise.resolve(jsonResponse([heldSubscription()])),
      open: openState([openPosition({ strategy_id: "99999999-9999-4999-8999-999999999999", markets: ["AAVEUSDT"] })]),
    });
    open();

    const row = await screen.findByTestId("subscription-row");
    await waitFor(() => expect(within(row).queryByText(i18n.t("positions.state.loading"))).not.toBeInTheDocument());
    expect(within(row).queryByRole("list")).not.toBeInTheDocument();
  });

  it("shows no chip for a strategy that holds nothing of the reader's", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])), open: openState() });
    open();

    const row = await screen.findByTestId("subscription-row");
    await waitFor(() => expect(within(row).queryByText(i18n.t("positions.state.loading"))).not.toBeInTheDocument());
    expect(within(row).queryByRole("list")).not.toBeInTheDocument();
  });
});

describe("the sort of My subscriptions", () => {
  const ID_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
  const ID_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
  const ID_C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";

  /** Alpha: subscribed latest, 5 % return; Bravo: subscribed first, 20 %; Charlie: no public record at all. */
  function listOf() {
    return {
      held: () =>
        Promise.resolve(
          jsonResponse([
            heldSubscription({ id: "h-a", strategy_id: ID_A, strategy_name: "Alpha", created_at: "2026-10-20T10:00:00Z" }),
            heldSubscription({ id: "h-b", strategy_id: ID_B, strategy_name: "Bravo", created_at: "2026-09-01T10:00:00Z" }),
            heldSubscription({ id: "h-c", strategy_id: ID_C, strategy_name: "Charlie", created_at: "2026-10-01T10:00:00Z" }),
          ]),
        ),
      publics: () =>
        Promise.resolve(
          jsonResponse([
            publicStrategy({ id: ID_A, name: "Alpha", unleveraged_return_before_fees: "0.05", closed_trade_count: 2, subscribers: 9, live_subscribers: 3, capital: "10" }),
            publicStrategy({ id: ID_B, name: "Bravo", unleveraged_return_before_fees: "0.20", closed_trade_count: 8, subscribers: 4, live_subscribers: 1, capital: "999" }),
          ]),
        ),
    };
  }

  const names = () =>
    screen.getAllByTestId("subscription-row").map((row) => within(row).getAllByRole("link")[0]?.textContent);
  const press = (name: string) => fireEvent.click(screen.getByRole("button", { name }));

  async function start() {
    serve(listOf());
    open();
    await screen.findAllByTestId("subscription-row");
    await waitFor(() => expect(screen.getAllByTestId("subscription-trades")[0]).not.toHaveTextContent("…"));
  }

  it("orders by the strategy's return, largest first, a seat with no public record last", async () => {
    await start();

    expect(names()).toEqual(["Bravo", "Alpha", "Charlie"]);
    press("Return, descending");
    expect(names()).toEqual(["Alpha", "Bravo", "Charlie"]);
  });

  it("orders by the time subscribed, the longest first, and not by the strategy's own age", async () => {
    await start();

    press("Age");

    expect(names()).toEqual(["Bravo", "Charlie", "Alpha"]);
    press("Age, descending");
    expect(names()).toEqual(["Alpha", "Charlie", "Bravo"]);
  });

  it("orders by closed trades, subscribers and capital the same way", async () => {
    await start();

    press("Closed trades");
    expect(names()).toEqual(["Bravo", "Alpha", "Charlie"]);
    press("Subscribers");
    expect(names()).toEqual(["Alpha", "Bravo", "Charlie"]);
    press("Capital");
    expect(names()).toEqual(["Bravo", "Alpha", "Charlie"]);
  });
});

describe("the list of My subscriptions", () => {
  it("points an empty list at Explore", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([])) });
    open();

    expect(await screen.findByText(i18n.t("strategies.subscriptions.empty"))).toBeInTheDocument();
    expect(screen.getByRole("link", { name: i18n.t("strategies.subscriptions.explore") })).toHaveAttribute(
      "href",
      "/strategies/explore",
    );
  });

  it("reads a failed list as an error, never as an empty one", async () => {
    serve({ held: () => Promise.resolve(jsonResponse({ detail: "down" }, 500)) });
    open();

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.subscriptions.error"));
    expect(screen.queryByText(i18n.t("strategies.subscriptions.empty"))).not.toBeInTheDocument();
  });

  it("says it is loading while the list is on its way", async () => {
    serve({ held: () => new Promise<Response>(() => undefined) });
    open();

    expect(await screen.findByText(i18n.t("strategies.subscriptions.loading"))).toBeInTheDocument();
  });
});
