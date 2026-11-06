import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import { DANGER_CONTROL } from "@/shared/ui/danger-control";
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
  leave?: () => Promise<Response>;
  preview?: Record<string, unknown> | ((url: string) => Record<string, unknown>);
}

function serve({ strategy, held, pools, me, subscribe, leave, preview }: Serve = {}) {
  return stubApi({ kind: "ok", body: {} }, [], pools ?? { kind: "ok", body: [pool("bybit")] }, {}, (url, init) => {
    if (url.endsWith(`/api/public/strategies/${ID}`)) {
      return strategy?.() ?? Promise.resolve(jsonResponse(publicStrategy({ id: ID })));
    }
    if (url.endsWith("/api/subscriptions/held")) return held?.() ?? Promise.resolve(jsonResponse([]));
    if (url.endsWith("/leave") && init?.method === "POST") return leave?.() ?? Promise.resolve(jsonResponse({}));
    if (url.includes("/api/subscriptions/") && init?.method === "PATCH") {
      return Promise.resolve(jsonResponse(heldSubscription({ strategy_id: ID, leverage: 4 })));
    }
    if (url.endsWith("/api/subscriptions") && init?.method === "POST") {
      return subscribe?.() ?? Promise.resolve(jsonResponse(subscriptionOf(ID, "100"), 201));
    }
    if (url.includes(`/strategies/${ID}/share-preview`)) {
      const body = typeof preview === "function" ? preview(url) : preview;
      return Promise.resolve(jsonResponse(body ?? unsyncedSharePreview(ID)));
    }
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

  it("shows the author's description above the figures, line breaks kept, under its own heading", async () => {
    const text = "Trend follower.\nRecommended leverage: x3.";
    serve({ strategy: () => Promise.resolve(jsonResponse(publicStrategy({ id: ID, description: text }))) });
    open();
    await screen.findByRole("heading", { level: 1, name: "Alpha" });

    const section = screen.getByTestId("public-description");
    expect(section).toHaveTextContent(/Trend follower\.\s*Recommended leverage: x3\./);
    expect(within(section).getByRole("heading", { level: 2, name: "About this strategy" })).toBeInTheDocument();
    const body = within(section).getByText(/Trend follower/);
    expect(body.textContent).toBe(text);
    expect(body).toHaveClass("whitespace-pre-line", "break-words");
    expect(section.compareDocumentPosition(screen.getByTestId("public-return")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: "Alpha" }).compareDocumentPosition(section)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it("names the description's heading in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    serve({ strategy: () => Promise.resolve(jsonResponse(publicStrategy({ id: ID, description: "Seguidor de tendencia." }))) });
    open();
    await screen.findByRole("heading", { level: 1, name: "Alpha" });

    expect(within(screen.getByTestId("public-description")).getByRole("heading", { name: "Acerca de esta estrategia" })).toBeInTheDocument();
    await act(() => i18n.changeLanguage("en"));
  });

  it("draws nothing for a strategy with no description", async () => {
    serve();
    open();
    await screen.findByRole("heading", { level: 1, name: "Alpha" });

    expect(screen.queryByTestId("public-description")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "About this strategy" })).not.toBeInTheDocument();
  });

  it("shows markup and Markdown literally: no element is created from the text", async () => {
    const text = "<b>x</b> <img src=x onerror=alert(1)> <script>alert(1)</script>\n[link](nope) **bold** javascript:alert(1) www.example.org";
    serve({ strategy: () => Promise.resolve(jsonResponse(publicStrategy({ id: ID, description: text }))) });
    open();
    await screen.findByRole("heading", { level: 1, name: "Alpha" });

    const section = screen.getByTestId("public-description");
    expect(within(section).getByText(/<b>x<\/b>/).textContent).toBe(text);
    expect(section.querySelector("b, img, script, strong, a")).toBeNull();
    expect(within(section).queryByRole("link")).not.toBeInTheDocument();
  });

  it("turns http and https URLs in the description into links, the text around them untouched", async () => {
    const text = "Read https://example.com/guide.\nOr (http://example.org/x), then javascript:alert(1).";
    serve({ strategy: () => Promise.resolve(jsonResponse(publicStrategy({ id: ID, description: text }))) });
    open();
    await screen.findByRole("heading", { level: 1, name: "Alpha" });

    const section = screen.getByTestId("public-description");
    const first = within(section).getByRole("link", { name: "https://example.com/guide" });
    expect(first).toHaveAttribute("href", "https://example.com/guide");
    expect(first).toHaveAttribute("target", "_blank");
    expect(first).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(section).getByRole("link", { name: "http://example.org/x" })).toHaveAttribute("href", "http://example.org/x");
    expect(within(section).getAllByRole("link")).toHaveLength(2);
    expect(section.querySelector("p")?.textContent).toBe(text);
    expect(section.querySelector("p")).toHaveClass("whitespace-pre-line", "break-words");
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

  it("while seated, replaces Subscribe with the share and leverage settings and Leave", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription({ strategy_id: ID, leverage: 2 })])) });
    open();

    const leave = await screen.findByRole("button", { name: i18n.t("strategies.subscriptions.leave") });
    expect(screen.getByRole("textbox", { name: i18n.t("strategies.detail.share.label") })).toHaveValue("30");
    expect(screen.getByRole("textbox", { name: i18n.t("strategies.leverage.label") })).toHaveValue("2");
    expect(leave.className).toBe(DANGER_CONTROL);
    expect(screen.queryByRole("button", { name: i18n.t("strategies.subscribe.submit") })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 2, name: i18n.t("strategies.subscribe.title") })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /My subscriptions/ })).not.toBeInTheDocument();
  });

  it("without a seat, still offers Subscribe and neither setting nor Leave", async () => {
    serve();
    open();

    expect(await subscribeButton()).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: i18n.t("strategies.leverage.label") })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: i18n.t("strategies.subscriptions.leave") })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: i18n.t("strategies.subscribe.title") })).toBeInTheDocument();
  });

  it("saves the seat's share and leverage from the page, each on its own", async () => {
    const row = heldSubscription({ strategy_id: ID, leverage: 2 });
    const fetchMock = serve({ held: () => Promise.resolve(jsonResponse([row])) });
    open();

    await screen.findByRole("button", { name: i18n.t("strategies.subscriptions.leave") });
    fireEvent.change(screen.getByRole("textbox", { name: i18n.t("strategies.leverage.label") }), {
      target: { value: "4" },
    });
    fireEvent.click(
      within(screen.getByRole("region", { name: i18n.t("strategies.leverage.label") })).getByRole("button", {
        name: i18n.t("strategies.leverage.save"),
      }),
    );

    await waitFor(() =>
      expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "PATCH")).toHaveLength(1),
    );
    const [url, init] = fetchMock.mock.calls.find(([, call]) => call?.method === "PATCH") as [string, RequestInit];
    expect(String(url)).toBe(`/api/subscriptions/${row.id}`);
    expect(init.body).toBe('{"leverage":4}');
  });

  it("leaving from the page asks first, then sends the leave and offers Subscribe again", async () => {
    let left = false;
    const fetchMock = serve({
      held: () => Promise.resolve(jsonResponse(left ? [] : [heldSubscription({ strategy_id: ID })])),
      leave: () => {
        left = true;
        return Promise.resolve(jsonResponse({}, 200));
      },
    });
    open();

    fireEvent.click(await screen.findByRole("button", { name: i18n.t("strategies.subscriptions.leave") }));
    const dialog = await screen.findByRole("dialog", { name: i18n.t("strategies.leave.confirmTitle", { name: "Alpha" }) });
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/leave"))).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole("button", { name: i18n.t("strategies.leave.confirm") }));

    expect(await subscribeButton()).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/leave"))).toHaveLength(1);
  });

  it("a seat that is leaving reads as it stands: no Leave, nothing to save, and the page says so", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription({ strategy_id: ID, status: "LEAVING" })])) });
    open();

    expect(await screen.findByRole("heading", { level: 2, name: i18n.t("strategies.subscribe.seatTitle") })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: i18n.t("strategies.subscriptions.leave") })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: i18n.t("strategies.subscribe.submit") })).not.toBeInTheDocument();
    expect(screen.getByText(i18n.t("strategies.detail.share.leaving"))).toBeInTheDocument();
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

  it("starts from no share at all: 0, a hint asking for one, no refusal, nothing to press (decision 39)", async () => {
    const fetchMock = serve();
    open();

    const field = await shareField();
    expect(field).toHaveValue("0");
    expect(field).toHaveAttribute("aria-invalid", "false");
    expect(screen.getByText(i18n.t("strategies.detail.share.startHint"))).toBeInTheDocument();
    expect(screen.queryByText(i18n.t("strategies.detail.share.outOfRange"))).not.toBeInTheDocument();
    expect(screen.queryByText(i18n.t("strategies.detail.share.amountError"))).not.toBeInTheDocument();
    expect(await subscribeButton()).toBeDisabled();
    fireEvent.submit(field.closest("form") as HTMLFormElement);
    await whatWasPressedHasRun();
    expect(posts(fetchMock)).toHaveLength(0);
  });

  it("sends the share typed over the starting 0 as a string", async () => {
    const fetchMock = serve();
    open();

    fireEvent.change(await shareField(), { target: { value: "25" } });
    expect(screen.queryByText(i18n.t("strategies.detail.share.startHint"))).not.toBeInTheDocument();
    fireEvent.click(await subscribeButton());

    await waitFor(() => expect(posts(fetchMock)).toHaveLength(1));
    const [, init] = posts(fetchMock)[0] as [string, RequestInit];
    expect(init.body).toBe(`{"strategy_id":"${ID}","allocation_percent":"25","leverage":1}`);
  });

  it("refuses a 0 typed by hand in words, drops the hint and sends nothing", async () => {
    const fetchMock = serve();
    open();

    const field = await shareField();
    fireEvent.change(field, { target: { value: "25" } });
    fireEvent.change(field, { target: { value: "0" } });

    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(i18n.t("strategies.detail.share.outOfRange"))).toBeInTheDocument();
    expect(screen.queryByText(i18n.t("strategies.detail.share.startHint"))).not.toBeInTheDocument();
    expect(await subscribeButton()).toBeDisabled();
    fireEvent.submit(field.closest("form") as HTMLFormElement);
    await whatWasPressedHasRun();
    expect(posts(fetchMock)).toHaveLength(0);
  });

  it("shows the amount of a whole share from the steps when the preview served no exact figure", async () => {
    const fetchMock = serve({
      preview: {
        ...unsyncedSharePreview(ID),
        balance: { total: "1000", observed_at: "2026-11-05T10:00:00Z", stale: false },
        exact: null,
        steps: Array.from({ length: 100 }, (_, index) => ({
          share: index + 1,
          amount: String((index + 1) * 10),
          below_pool_minimum: false,
        })),
      },
    });
    open();

    const field = await shareField();
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes(`/strategies/${ID}/share-preview`))).toBe(true),
    );
    await whatWasPressedHasRun();
    expect(screen.queryByText(i18n.t("strategies.detail.share.amountError"))).not.toBeInTheDocument();
    expect(screen.queryByText(/Margin:/)).not.toBeInTheDocument();

    fireEvent.change(field, { target: { value: "25" } });
    expect(await screen.findByText(/Margin: 250/)).toBeInTheDocument();
  });

  // I.4: the form shows the margin and, above 1x, the notional the server serves for the leverage chosen here.
  const previewAtLeverage = (url: string): Record<string, unknown> => {
    const params = new URL(url, "http://panel.test").searchParams;
    const share = params.get("share") ?? "0";
    const leverage = params.get("leverage");
    const amount = Number(share) * 10;
    return {
      ...unsyncedSharePreview(ID),
      balance: { total: "1000", observed_at: "2026-11-05T10:00:00Z", stale: false },
      exact: {
        share,
        amount: amount.toFixed(18),
        below_pool_minimum: false,
        notional: leverage === null ? null : (amount * Number(leverage)).toFixed(18),
      },
      steps: Array.from({ length: 100 }, (_, index) => ({
        share: index + 1,
        amount: String((index + 1) * 10),
        below_pool_minimum: false,
      })),
    };
  };
  const previewUrls = (fetchMock: ReturnType<typeof serve>) =>
    fetchMock.mock.calls.map(([url]) => String(url)).filter((url) => url.includes(`/strategies/${ID}/share-preview`));

  it("at x1 the form asks for no leverage and names the margin alone", async () => {
    const fetchMock = serve({ preview: previewAtLeverage });
    open();

    fireEvent.change(await shareField(), { target: { value: "25" } });

    expect(await screen.findByText("Margin: 250.00 USDT")).toBeInTheDocument();
    await whatWasPressedHasRun();
    expect(previewUrls(fetchMock).some((url) => url.includes("leverage="))).toBe(false);
    expect(screen.queryByText(/Notional/)).not.toBeInTheDocument();
  });

  it("above x1 the share is read at the leverage chosen in the same form, and the notional shows", async () => {
    const fetchMock = serve({ preview: previewAtLeverage });
    open();

    const leverage = await screen.findByRole("textbox", { name: i18n.t("strategies.leverage.label") });
    fireEvent.change(leverage, { target: { value: "6" } });
    fireEvent.change(await shareField(), { target: { value: "25" } });

    expect(await screen.findByText("Margin: 250.00 USDT · Notional: 1,500.00 USDT")).toBeInTheDocument();
    expect(previewUrls(fetchMock).some((url) => url.endsWith("?share=25&leverage=6"))).toBe(true);
  });

  it("sends the share the user typed, in plain form", async () => {
    const fetchMock = serve();
    open();

    fireEvent.change(await shareField(), { target: { value: "12,5" } });
    fireEvent.click(await subscribeButton());

    await waitFor(() => expect(posts(fetchMock)).toHaveLength(1));
    const [, init] = posts(fetchMock)[0] as [string, RequestInit];
    expect(init.body).toBe(`{"strategy_id":"${ID}","allocation_percent":"12.5","leverage":1}`);
  });

  it("offers a leverage that starts at x1 and sends the one the user chose, as a number, with the share", async () => {
    const fetchMock = serve();
    open();

    const leverage = await screen.findByRole("textbox", { name: i18n.t("strategies.leverage.label") });
    expect(leverage).toHaveValue("1");
    expect(screen.getByRole("slider", { name: i18n.t("strategies.leverage.label") })).toHaveValue("1");
    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.leverage.stop", { value: 10 }) }));
    expect(leverage).toHaveValue("10");
    fireEvent.change(leverage, { target: { value: "6" } });
    fireEvent.change(await shareField(), { target: { value: "100" } });
    fireEvent.click(await subscribeButton());

    await waitFor(() => expect(posts(fetchMock)).toHaveLength(1));
    const [, init] = posts(fetchMock)[0] as [string, RequestInit];
    expect(init.body).toBe(`{"strategy_id":"${ID}","allocation_percent":"100","leverage":6}`);
  });

  it.each(["0", "21", "2.5", ""])("refuses a leverage of %j in words and sends nothing", async (text) => {
    const fetchMock = serve();
    open();

    const leverage = await screen.findByRole("textbox", { name: i18n.t("strategies.leverage.label") });
    fireEvent.change(leverage, { target: { value: text } });

    expect(await subscribeButton()).toBeDisabled();
    expect(leverage).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(i18n.t("strategies.leverage.invalid"))).toBeInTheDocument();
    fireEvent.submit(leverage.closest("form") as HTMLFormElement);
    await whatWasPressedHasRun();
    expect(posts(fetchMock)).toHaveLength(0);
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

    fireEvent.change(await shareField(), { target: { value: "100" } });
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

    fireEvent.change(await shareField(), { target: { value: "100" } });
    fireEvent.click(await subscribeButton());

    expect(await screen.findByRole("button", { name: i18n.t("strategies.subscriptions.leave") })).toBeInTheDocument();
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

    fireEvent.change(await shareField(), { target: { value: "100" } });
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
