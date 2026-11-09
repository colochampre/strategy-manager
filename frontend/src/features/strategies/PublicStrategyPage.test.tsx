import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import { DANGER_CONTROL } from "@/shared/ui/danger-control";
import {
  emptyPerformance,
  heldSubscription,
  jsonResponse,
  pool,
  publicRecord,
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
  record?: () => Promise<Response>;
}

function serve({ strategy, held, pools, me, subscribe, leave, preview, record }: Serve = {}) {
  return stubApi({ kind: "ok", body: {} }, [], pools ?? { kind: "ok", body: [pool("bybit")] }, {}, (url, init) => {
    if (url.endsWith(`/api/public/strategies/${ID}`)) {
      return strategy?.() ?? Promise.resolve(jsonResponse(publicStrategy({ id: ID })));
    }
    if (url.endsWith(`/api/public/strategies/${ID}/record`)) {
      return record?.() ?? Promise.resolve(jsonResponse(publicRecord()));
    }
    if (url.includes(`/api/performance/strategies/${ID}`)) {
      return Promise.resolve(jsonResponse({ ...emptyPerformance("bybit", "usdt-m", "USDT"), strategy_id: ID, by_pair: [] }));
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
    await waitFor(() => expect(screen.getByTestId("public-return")).toHaveTextContent("+5.1%"));
    expect(screen.getByRole("link", { name: i18n.t("strategies.public.back") })).toHaveAttribute(
      "href",
      "/strategies/explore",
    );
  });

  it("shows the capital's dash, not words, where there is no return yet (owner, 2026-11-08)", async () => {
    serve({
      strategy: () =>
        Promise.resolve(
          jsonResponse(publicStrategy({ id: ID, closed_trade_count: 0, unleveraged_return_before_fees: "0" })),
        ),
      record: () =>
        Promise.resolve(jsonResponse(publicRecord({ origin: null, closed_trade_count: 0, curve: [], monthly: [], by_pair: [] }))),
    });
    open();

    await waitFor(() => expect(screen.getByTestId("public-return")).toHaveTextContent(/^—$/));
    expect(screen.getByTestId("public-deepest")).toHaveTextContent(/^—$/);
  });

  it("draws the strategy's record below the figures for a reader with no seat, with no selector", async () => {
    serve();
    open();

    expect(await screen.findByRole("heading", { name: "Performance" })).toBeInTheDocument();
    expect(await screen.findByRole("row", { name: /^SOLUSDT\b/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "My results" })).toBeNull();
    // The Subscribe section is where it was.
    expect(await subscribeButton()).toBeInTheDocument();
  });

  it.each([
    ["without a seat, Subscribe", undefined, "strategies.subscribe.title"],
    ["with a seat, Your subscription", [{ strategy_id: ID }], "strategies.subscribe.seatTitle"],
  ])(
    "%s is an aside beside the record, after it in reading order, as Strategy settings on an own strategy",
    async (_case, seats, title) => {
      serve(
        seats === undefined
          ? {}
          : { held: () => Promise.resolve(jsonResponse(seats.map((seat) => heldSubscription(seat)))) },
      );
      open();

      const aside = await screen.findByRole("complementary", { name: i18n.t(title) });
      const grid = aside.parentElement as HTMLElement;
      const column = grid.firstElementChild as HTMLElement;
      expect(grid.className).toContain("lg:grid-cols-[minmax(0,1fr)_25rem]");
      expect(column).not.toBe(aside);
      expect(column).toContainElement(screen.getByRole("heading", { level: 1, name: "Alpha" }));
      expect(column).toContainElement(await screen.findByRole("heading", { name: "Performance" }));
      expect(aside).not.toContainElement(screen.getByTestId("public-return"));
      // Stacked on a phone, the aside comes last, as on an own strategy.
      expect(column.compareDocumentPosition(aside) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    },
  );

  it("opens a subscriber's page on My results and keeps their seat settings", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription({ strategy_id: ID })])) });
    open();

    expect(await screen.findByRole("button", { name: "My results" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByRole("heading", { name: "Your subscription" })).toBeInTheDocument();
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

  it("draws the strategy's figures and its record's in one grid of the cards' icons, under Performance (L.10)", async () => {
    serve();
    open();

    const line = await screen.findByTestId("record-line");
    const performance = screen.getByRole("region", { name: i18n.t("strategies.report.title") });
    expect(performance).toContainElement(line);
    const ids = [...line.querySelectorAll("dd")].map((value) => value.getAttribute("data-testid"));
    expect(ids).toEqual([
      "public-age",
      "public-uptime",
      "public-trades",
      "public-return",
      "public-deepest",
      "public-winrate",
      "public-subscribers",
      "public-capital",
    ]);
    // The return and the fall follow the chart's range, read from the record (30D by default).
    await waitFor(() => expect(within(line).getByTestId("public-return")).toHaveTextContent("+5.1%"));
    expect(within(line).getByTestId("public-deepest")).toHaveTextContent("-2.0%");
    // The return and the capital each keep one (i), on that row.
    expect(within(line).getAllByRole("button", { name: i18n.t("strategies.public.returnInfo") })).toHaveLength(1);
    expect(within(line).getAllByRole("button", { name: i18n.t("strategies.public.capitalInfo") })).toHaveLength(1);
    expect(screen.getAllByTestId("public-return")).toHaveLength(1);
    // One row wherever the column holds it, each figure as wide as its own value; four a row where it does not
    // (L.11). The column's width decides, not the screen's: the page's aside takes a share of it.
    expect(line.parentElement).toHaveClass("@container");
    expect(line).toHaveClass(
      "grid-cols-4",
      "@[32rem]:grid-flow-col",
      "@[32rem]:grid-cols-none",
      "@[32rem]:auto-cols-max",
    );
    expect(line).not.toHaveClass("lg:grid-flow-col");
    expect(line).not.toHaveClass("lg:grid-cols-4");
  });

  it("explains the return and the capital on request, closed by default", async () => {
    serve();
    open();
    await screen.findByRole("heading", { level: 1, name: "Alpha" });

    // The return's explanation lives on the record line, once the record has been read.
    await screen.findByTestId("record-line");

    expect(screen.queryByText(i18n.t("strategies.public.returnHint"))).not.toBeInTheDocument();
    expect(screen.queryByText(i18n.t("strategies.public.capitalHint"))).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.public.returnInfo") }));
    expect(screen.getByText(i18n.t("strategies.public.returnHint"))).toBeInTheDocument();
    expect(screen.queryByText(i18n.t("strategies.public.capitalHint"))).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.public.capitalInfo") }));
    expect(screen.getByText(i18n.t("strategies.public.capitalHint"))).toBeInTheDocument();
  });

  it("explains the return once: one (i), on the one row of figures; no second figure card (L.10)", async () => {
    serve();
    open();
    const line = await screen.findByTestId("record-line");

    const infos = screen.getAllByRole("button", { name: i18n.t("strategies.public.returnInfo") });
    expect(infos).toHaveLength(1);
    expect(line).toContainElement(infos[0] as HTMLElement);
    expect(screen.getAllByRole("definition").every((value) => line.contains(value))).toBe(true);
    fireEvent.click(infos[0] as HTMLElement);
    expect(screen.getAllByText(i18n.t("strategies.public.returnHint"))).toHaveLength(1);
  });

  it("says whether the strategy runs, beside its name, as the cards do", async () => {
    serve({ strategy: () => Promise.resolve(jsonResponse(publicStrategy({ id: ID, enabled: true }))) });
    open();

    const pill = await screen.findByTestId("public-enabled");
    expect(pill).toHaveTextContent("Enabled");
    expect(pill).toHaveClass("border-gain", "text-gain");
    const title = screen.getByRole("heading", { level: 1, name: "Alpha" }).parentElement as HTMLElement;
    expect(title).toContainElement(pill);
    // The name and its mark share one centred line (L.11).
    expect(title).toHaveClass("items-center");
    expect(title).not.toHaveClass("items-baseline");
  });

  it("says disabled when the strategy does not run", async () => {
    serve({ strategy: () => Promise.resolve(jsonResponse(publicStrategy({ id: ID, enabled: false }))) });
    open();

    const pill = await screen.findByTestId("public-enabled");
    expect(pill).toHaveTextContent("Disabled");
    expect(pill).toHaveClass("text-ink-3");
    expect(pill).not.toHaveClass("text-gain");
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
    // The danger look of Disable and Archive, and the whole width of the aside like them.
    expect(leave.className).toBe(`${DANGER_CONTROL} w-full justify-center`);
    // The aside's sections sit closer (gap-2, was gap-5).
    expect(leave.closest("aside")).toHaveClass("gap-2");
    expect(leave.closest("aside")).not.toHaveClass("gap-5");
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

  it("leaving a strategy turned private says it is off the list, and offers no Subscribe it would refuse (J.1)", async () => {
    let left = false;
    serve({
      strategy: () =>
        Promise.resolve(left ? jsonResponse({ detail: "no such strategy" }, 404) : jsonResponse(publicStrategy({ id: ID }))),
      held: () => Promise.resolve(jsonResponse(left ? [] : [heldSubscription({ strategy_id: ID })])),
      leave: () => {
        left = true;
        return Promise.resolve(jsonResponse({}, 200));
      },
    });
    open();

    fireEvent.click(await screen.findByRole("button", { name: i18n.t("strategies.subscriptions.leave") }));
    const dialog = await screen.findByRole("dialog", { name: i18n.t("strategies.leave.confirmTitle", { name: "Alpha" }) });
    fireEvent.click(within(dialog).getByRole("button", { name: i18n.t("strategies.leave.confirm") }));

    expect(await screen.findByText(i18n.t("strategies.public.notFound"))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: i18n.t("strategies.subscribe.submit") })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Alpha" })).not.toBeInTheDocument();
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

    await waitFor(() => expect(screen.getByTestId("public-return")).toHaveTextContent("+5.1%"));
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
    await waitFor(() => expect(screen.getByTestId("public-return")).toHaveTextContent("+5.1%"));
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

/** The seat's Leave lives on this page alone since My subscriptions became a summary (I.14). */
describe("leaving from the seat", () => {
  const seated = () => Promise.resolve(jsonResponse([heldSubscription({ strategy_id: ID })]));
  const leaveName = () => i18n.t("strategies.subscriptions.leave");
  /** Inside the dialog: the aside behind it holds a button of the same name, which a real modal makes inert. */
  const confirmButton = () =>
    within(screen.getByRole("dialog")).getByRole("button", { name: i18n.t("strategies.leave.confirm") });
  const leaves = (fetchMock: ReturnType<typeof stubApi>) =>
    fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/leave"));

  it("asks first: opening the dialog sends nothing, and says what happens to a position", async () => {
    const fetchMock = serve({ held: seated });
    open();

    fireEvent.click(await screen.findByRole("button", { name: leaveName() }));

    const dialog = await screen.findByRole("dialog", { name: i18n.t("strategies.leave.confirmTitle", { name: "Alpha" }) });
    expect(within(dialog).getByText(i18n.t("strategies.leave.confirmBody", { name: "Alpha" }))).toBeInTheDocument();
    expect(within(dialog).getByText(i18n.t("strategies.leave.privateNote"))).toBeInTheDocument();
    expect(leaves(fetchMock)).toHaveLength(0);
  });

  it.each([
    ["the cancel button", () => fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.leave.cancel") }))],
    ["Escape", () => fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" })],
    ["the browser's cancel", () => fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }))],
  ])("%s sends nothing and closes", async (_name, dismiss) => {
    const fetchMock = serve({ held: seated });
    open();

    fireEvent.click(await screen.findByRole("button", { name: leaveName() }));
    dismiss();

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(leaves(fetchMock)).toHaveLength(0);
  });

  it("confirming posts the leave of that subscription", async () => {
    const row = heldSubscription({ strategy_id: ID });
    const fetchMock = serve({ held: () => Promise.resolve(jsonResponse([row])) });
    open();

    fireEvent.click(await screen.findByRole("button", { name: leaveName() }));
    fireEvent.click(confirmButton());

    await waitFor(() => expect(leaves(fetchMock).map(([url]) => String(url))).toEqual([
      expect.stringContaining(`/api/subscriptions/${row.id}/leave`),
    ]));
  });

  it("a position still open leaves the seat in place, marked as leaving, with the dialog closed", async () => {
    const row = heldSubscription({ strategy_id: ID });
    let left = false;
    serve({
      held: () => Promise.resolve(jsonResponse([left ? { ...row, status: "LEAVING" } : row])),
      leave: () => {
        left = true;
        return Promise.resolve(jsonResponse({ ...row, status: "LEAVING" }));
      },
    });
    open();

    fireEvent.click(await screen.findByRole("button", { name: leaveName() }));
    fireEvent.click(confirmButton());

    expect(await screen.findByText(i18n.t("strategies.subscriptions.leaving"))).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("holds while the leave is on its way: nothing presses it twice and Escape does not close it", async () => {
    serve({ held: seated, leave: () => new Promise<Response>(() => undefined) });
    open();

    fireEvent.click(await screen.findByRole("button", { name: leaveName() }));
    fireEvent.click(confirmButton());

    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByRole("button", { name: i18n.t("strategies.leave.pending") })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: i18n.t("strategies.leave.cancel") })).toBeDisabled();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("opening the dialog again forgets the last refusal", async () => {
    serve({ held: seated, leave: () => Promise.resolve(jsonResponse({ detail: "boom" }, 500)) });
    open();

    fireEvent.click(await screen.findByRole("button", { name: leaveName() }));
    fireEvent.click(confirmButton());
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.leave.cancel") }));
    fireEvent.click(screen.getByRole("button", { name: leaveName() }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    [409, { error: "AUTHOR_CANNOT_LEAVE", message: "no" }, "strategies.leave.errors.author"],
    [409, { error: "SUBSCRIPTION_NOT_ACTIVE", message: "no" }, "strategies.leave.errors.notActive"],
    [404, "no subscription", "strategies.leave.errors.gone"],
    [500, "boom", "strategies.leave.errors.generic"],
  ])("a %i refusal is in words, inside the dialog", async (status, detail, key) => {
    serve({ held: seated, leave: () => Promise.resolve(jsonResponse({ detail }, status)) });
    open();

    fireEvent.click(await screen.findByRole("button", { name: leaveName() }));
    fireEvent.click(confirmButton());

    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(i18n.t(key));
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
