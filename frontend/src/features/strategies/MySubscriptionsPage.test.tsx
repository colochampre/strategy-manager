import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import {
  heldSubscription,
  jsonResponse,
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
}

function serve({ held, publics }: Serve) {
  return stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) => {
    if (url.endsWith("/api/subscriptions/held")) return held();
    if (url.endsWith("/api/public/strategies")) {
      return publics?.() ?? Promise.resolve(jsonResponse([publicStrategy({ id: STRATEGY_ID })]));
    }
    if (url.includes(`/strategies/${STRATEGY_ID}/share-preview`)) {
      return Promise.resolve(jsonResponse(unsyncedSharePreview(STRATEGY_ID)));
    }
    return undefined;
  });
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

  it("draws the strategy's public figures: closed trades, return, people trading it live and capital", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])) });
    open();

    const row = await screen.findByTestId("subscription-row");
    expect(await within(row).findByTestId("public-trades")).toHaveTextContent(/^3$/);
    expect(within(row).getByTestId("public-return")).toHaveTextContent(/^\+12\.5\s?%$/);
    expect(within(row).getByTestId("public-live")).toHaveTextContent(/^2$/);
    expect(within(row).getByTestId("public-capital")).toBeInTheDocument();
    // The strategy's own age is not drawn: the card counts the reader's time in it instead.
    expect(within(row).queryByTestId("public-age")).not.toBeInTheDocument();
  });

  it("counts the age from the day the reader subscribed, not from the strategy's creation", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-06T12:00:00Z"));
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription({ created_at: "2026-10-27T10:00:00Z" })])) });
    open();

    const age = await screen.findByTestId("subscription-age");
    expect(age).toHaveTextContent(/^10d$/);
    const figure = age.parentElement as HTMLElement;
    expect(within(figure).getByRole("img", { name: i18n.t("strategies.subscriptions.age") })).toBeInTheDocument();
  });

  it("adds the share of the pool and the leverage, each under its icon, the share in plain form", async () => {
    serve({
      held: () => Promise.resolve(jsonResponse([heldSubscription({ allocation_percent: "30.000000", leverage: 4 })])),
    });
    open();

    const share = await screen.findByTestId("subscription-share");
    expect(share).toHaveTextContent(/^30%$/);
    expect(
      within(share.parentElement as HTMLElement).getByRole("img", { name: i18n.t("strategies.subscriptions.share") }),
    ).toBeInTheDocument();
    const leverage = screen.getByTestId("subscription-leverage");
    expect(leverage).toHaveTextContent(/^x4$/);
    expect(
      within(leverage.parentElement as HTMLElement).getByRole("img", { name: i18n.t("strategies.subscriptions.leverage") }),
    ).toBeInTheDocument();
  });

  it("offers no Leave, nor any other button: the seat is managed on the strategy's page", async () => {
    const fetchMock = serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])) });
    open();

    const row = await screen.findByTestId("subscription-row");
    await within(row).findByTestId("public-trades");
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
    expect(screen.queryByTestId("public-trades")).not.toBeInTheDocument();
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
    expect(screen.queryByTestId("public-trades")).not.toBeInTheDocument();
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
