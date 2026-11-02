import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import {
  heldSubscription,
  jsonResponse,
  pool,
  publicStrategy,
  renderAt,
  resetExchangeScope,
  setViewport,
  stubApi,
  subscriptionOf,
  unlock,
  unsyncedSharePreview,
} from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";

interface Serve {
  strategy?: () => Promise<Response>;
  held?: () => Promise<Response>;
  pools?: Parameters<typeof stubApi>[2];
  me?: Record<string, unknown>;
  subscribe?: () => Promise<Response>;
}

function serve({ strategy, held, pools, me, subscribe }: Serve = {}) {
  return stubApi({ kind: "ok", body: {} }, [], pools ?? { kind: "ok", body: [pool("bybit")] }, {}, (url, init) => {
    if (url.endsWith(`/api/public/strategies/${ID}`)) {
      return strategy?.() ?? Promise.resolve(jsonResponse(publicStrategy({ id: ID })));
    }
    if (url.endsWith("/api/subscriptions/held")) return held?.() ?? Promise.resolve(jsonResponse([]));
    if (url.endsWith("/api/subscriptions") && init?.method === "POST") {
      return subscribe?.() ?? Promise.resolve(jsonResponse(subscriptionOf(ID, "100"), 201));
    }
    if (url.includes(`/strategies/${ID}/share-preview`)) return Promise.resolve(jsonResponse(unsyncedSharePreview(ID)));
    if (url.endsWith("/api/me")) {
      return Promise.resolve(
        jsonResponse({ email: "a@example.com", is_admin: true, mode: "LIVE", dry_run_brake: false, ...me }),
      );
    }
    return undefined;
  });
}

function open() {
  renderAt(<AppRoutes />, `/strategies/explore/${ID}`);
}

const subscribeButton = () => screen.findByRole("button", { name: i18n.t("strategies.subscribe.submit") });
const shareField = () => screen.findByRole("textbox", { name: i18n.t("strategies.detail.share.label") });

/** A mutation sends its request after the press returns, so "nothing was sent" can only be read after this. */
const whatWasPressedHasRun = () =>
  act(
    () =>
      new Promise<void>((resolve) => {
        setTimeout(resolve, 0);
      }),
  );

function posts(fetchMock: ReturnType<typeof stubApi>) {
  return fetchMock.mock.calls.filter(
    ([url, init]) => String(url).endsWith("/api/subscriptions") && init?.method === "POST",
  );
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
  setViewport("wide");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the public page", () => {
  it("names the strategy, its author, its market and its figures, and the way back", async () => {
    serve();
    open();

    expect(await screen.findByRole("heading", { level: 1, name: "Alpha" })).toBeInTheDocument();
    expect(screen.getByTestId("public-origin")).toHaveTextContent(i18n.t("strategies.public.by", { name: "Ana" }));
    expect(screen.getByTestId("public-market")).toHaveTextContent("bybit · usdt-m · USDT");
    expect(screen.getByTestId("public-return")).toHaveTextContent("+12.5%");
    expect(screen.getByRole("link", { name: i18n.t("strategies.public.back") })).toHaveAttribute(
      "href",
      "/strategies/explore",
    );
  });

  it("explains the return and the capital on request, closed by default", async () => {
    serve();
    open();
    await screen.findByRole("heading", { level: 1, name: "Alpha" });

    expect(screen.queryByText(i18n.t("strategies.public.returnHint"))).not.toBeInTheDocument();
    expect(screen.queryByText(i18n.t("strategies.public.capitalHint"))).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.public.returnInfo") }));
    expect(screen.getByText(i18n.t("strategies.public.returnHint"))).toBeInTheDocument();
    expect(screen.queryByText(i18n.t("strategies.public.capitalHint"))).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.public.capitalInfo") }));
    expect(screen.getByText(i18n.t("strategies.public.capitalHint"))).toBeInTheDocument();
  });

  it("reads a 404 as off the list, in plain words and not as a fault", async () => {
    serve({ strategy: () => Promise.resolve(jsonResponse({ detail: "no such strategy" }, 404)) });
    open();

    expect(await screen.findByText(i18n.t("strategies.public.notFound"))).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: i18n.t("strategies.public.back") })).toBeInTheDocument();
  });

  it("reads any other failure as a fault", async () => {
    serve({ strategy: () => Promise.resolve(jsonResponse({ detail: "down" }, 500)) });
    open();

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.public.error"));
    expect(screen.queryByText(i18n.t("strategies.public.notFound"))).not.toBeInTheDocument();
  });

  it("says it is loading while the strategy is on its way", async () => {
    serve({ strategy: () => new Promise<Response>(() => undefined) });
    open();

    expect(await screen.findByText(i18n.t("strategies.public.loading"))).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("draws no list tabs: it is one strategy, not a list", async () => {
    serve();
    open();

    await screen.findByRole("heading", { level: 1, name: "Alpha" });
    expect(screen.queryByRole("navigation", { name: i18n.t("strategies.tabs.label") })).not.toBeInTheDocument();
  });
});

describe("whether this user can subscribe", () => {
  it("sends the author to their own strategy, with no form", async () => {
    serve({ me: { display_name: "Ana" } });
    open();

    expect(await screen.findByText(i18n.t("strategies.subscribe.yours"))).toBeInTheDocument();
    expect(screen.getByRole("link", { name: i18n.t("strategies.subscribe.openYours") })).toHaveAttribute(
      "href",
      `/strategies/${ID}`,
    );
    expect(screen.queryByRole("button", { name: i18n.t("strategies.subscribe.submit") })).not.toBeInTheDocument();
  });

  it("knows an author by their subscription too", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription({ strategy_id: ID, authored: true })])) });
    open();

    expect(await screen.findByText(i18n.t("strategies.subscribe.yours"))).toBeInTheDocument();
  });

  it("sends someone already subscribed to My subscriptions, with no form", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription({ strategy_id: ID })])) });
    open();

    expect(await screen.findByText(i18n.t("strategies.subscribe.held", { share: "30" }))).toBeInTheDocument();
    expect(screen.getByRole("link", { name: i18n.t("strategies.subscribe.manage") })).toHaveAttribute("href", "/strategies");
    expect(screen.queryByRole("button", { name: i18n.t("strategies.subscribe.submit") })).not.toBeInTheDocument();
  });

  it("writes the share in plain form, however the server wrote it", async () => {
    serve({
      held: () => Promise.resolve(jsonResponse([heldSubscription({ strategy_id: ID, allocation_percent: "30.000000" })])),
    });
    open();

    expect(await screen.findByText(i18n.t("strategies.subscribe.held", { share: "30" }))).toBeInTheDocument();
  });

  it("is not fooled by a subscription to another strategy", async () => {
    serve({
      held: () =>
        Promise.resolve(jsonResponse([heldSubscription({ strategy_id: "22222222-2222-4222-8222-222222222222" })])),
    });
    open();

    expect(await subscribeButton()).toBeInTheDocument();
  });

  it("with no pool on the strategy's market, the user reads the figures and is told what is missing, in words", async () => {
    serve({ pools: { kind: "ok", body: [] } });
    open();

    expect(await screen.findByTestId("public-return")).toHaveTextContent("+12.5%");
    expect(await screen.findByText(i18n.t("strategies.subscribe.needsKey", { exchange: "Bybit" }))).toBeInTheDocument();
    expect(screen.getByRole("link", { name: i18n.t("strategies.subscribe.addKey") })).toHaveAttribute("href", "/settings");
    expect(screen.queryByRole("button", { name: i18n.t("strategies.subscribe.submit") })).not.toBeInTheDocument();
  });

  it.each([
    ["another exchange", pool("binance")],
    ["another venue", pool("bybit", "spot")],
    ["another currency", pool("bybit", "usdt-m", "USDC")],
    ["a pool whose key was deleted", { ...pool("bybit"), enabled: false }],
  ])("%s does not count as a pool for it", async (_name, held) => {
    serve({ pools: { kind: "ok", body: [held] } });
    open();

    expect(await screen.findByText(i18n.t("strategies.subscribe.needsKey", { exchange: "Bybit" }))).toBeInTheDocument();
  });

  it.each([
    ["the pools", { pools: { kind: "status", status: 500 } as Parameters<typeof stubApi>[2] }],
    ["the subscriptions", { held: () => Promise.resolve(jsonResponse({ detail: "down" }, 500)) }],
  ])("a failed read of %s offers no form and says so", async (_name, stubs) => {
    serve(stubs);
    open();

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.subscribe.readFailed"));
    expect(screen.queryByRole("button", { name: i18n.t("strategies.subscribe.submit") })).not.toBeInTheDocument();
    expect(screen.getByTestId("public-return")).toHaveTextContent("+12.5%");
  });

  it("offers nothing to press while those reads are on their way", async () => {
    serve({ held: () => new Promise<Response>(() => undefined) });
    open();

    expect(await screen.findByText(i18n.t("strategies.subscribe.reading"))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: i18n.t("strategies.subscribe.submit") })).not.toBeInTheDocument();
  });
});

describe("subscribing", () => {
  it("says the capital joins a public sum, in plain sight", async () => {
    serve();
    open();

    await subscribeButton();
    expect(screen.getByText(i18n.t("strategies.subscribe.publicSum"))).toBeInTheDocument();
  });

  it("starts from a full share and sends it as a string", async () => {
    const fetchMock = serve();
    open();

    expect(await shareField()).toHaveValue("100");
    fireEvent.click(await subscribeButton());

    await waitFor(() => expect(posts(fetchMock)).toHaveLength(1));
    const [, init] = posts(fetchMock)[0] as [string, RequestInit];
    expect(init.body).toBe(`{"strategy_id":"${ID}","allocation_percent":"100"}`);
  });

  it("sends the share the user typed, in plain form", async () => {
    const fetchMock = serve();
    open();

    fireEvent.change(await shareField(), { target: { value: "12,5" } });
    fireEvent.click(await subscribeButton());

    await waitFor(() => expect(posts(fetchMock)).toHaveLength(1));
    const [, init] = posts(fetchMock)[0] as [string, RequestInit];
    expect(init.body).toBe(`{"strategy_id":"${ID}","allocation_percent":"12.5"}`);
  });

  it("asks for the amount on this strategy, not on any other", async () => {
    const fetchMock = serve();
    open();

    await subscribeButton();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes(`/strategies/${ID}/share-preview`))).toBe(true);
  });

  it("refuses a share that is no share, and sends nothing", async () => {
    const fetchMock = serve();
    open();

    fireEvent.change(await shareField(), { target: { value: "150" } });

    expect(await subscribeButton()).toBeDisabled();
    expect(screen.getByText(i18n.t("strategies.detail.share.outOfRange"))).toBeInTheDocument();
    fireEvent.submit((await shareField()).closest("form") as HTMLFormElement);
    await whatWasPressedHasRun();
    expect(posts(fetchMock)).toHaveLength(0);
  });

  it("sends one request however often it is pressed while that one is on its way", async () => {
    const fetchMock = serve({ subscribe: () => new Promise<Response>(() => undefined) });
    open();

    fireEvent.click(await subscribeButton());
    expect(await screen.findByRole("button", { name: i18n.t("strategies.subscribe.pending") })).toBeDisabled();
    fireEvent.submit((await shareField()).closest("form") as HTMLFormElement);
    await whatWasPressedHasRun();

    expect(posts(fetchMock)).toHaveLength(1);
  });

  it("once subscribed, the page says so and the form is gone", async () => {
    let subscribed = false;
    serve({
      held: () =>
        Promise.resolve(jsonResponse(subscribed ? [heldSubscription({ strategy_id: ID, allocation_percent: "100" })] : [])),
      subscribe: () => {
        subscribed = true;
        return Promise.resolve(jsonResponse(subscriptionOf(ID, "100"), 201));
      },
    });
    open();

    fireEvent.click(await subscribeButton());

    expect(await screen.findByText(i18n.t("strategies.subscribe.held", { share: "100" }))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: i18n.t("strategies.subscribe.submit") })).not.toBeInTheDocument();
  });

  it.each([
    [409, { error: "NO_POOL_FOR_MARKET", message: "no" }, "strategies.subscribe.refused.needsKey"],
    [409, { error: "ALREADY_SUBSCRIBED", message: "no" }, "strategies.subscribe.refused.already"],
    [409, { error: "STRATEGY_ARCHIVED", message: "no" }, "strategies.subscribe.refused.archived"],
    [409, { error: "SOMETHING_NEW", message: "no" }, "strategies.subscribe.refused.failed"],
    [404, "no strategy", "strategies.subscribe.refused.gone"],
    [422, "bad share", "strategies.detail.share.outOfRange"],
    [500, "boom", "strategies.subscribe.refused.failed"],
  ])("a %i refusal is in words", async (status, detail, key) => {
    serve({ subscribe: () => Promise.resolve(jsonResponse({ detail }, status)) });
    open();

    fireEvent.click(await subscribeButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t(key));
  });
});

describe("the Authored list", () => {
  it("still lives under its own tab", async () => {
    stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [pool("bybit")] }, {}, (url) =>
      url.includes("/api/strategies") ? Promise.resolve(jsonResponse([])) : undefined,
    );
    renderAt(<AppRoutes />, "/strategies/authored");

    const tabs = await screen.findByRole("navigation", { name: i18n.t("strategies.tabs.label") });
    expect(within(tabs).getByRole("link", { name: i18n.t("strategies.tabs.authored") })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(await screen.findByRole("button", { name: i18n.t("strategies.new.open") })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });
});
