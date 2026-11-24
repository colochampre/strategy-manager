import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { ExchangeTabs } from "@/shared/layout/ExchangeTabs";
import {
  emptyKey,
  jsonResponse,
  lock,
  pool,
  renderAt,
  resetExchangeScope,
  SIGNED_UP,
  storedKey,
  strategyRoute,
  stubApi,
  type CredentialsStub,
  type ExtraRoute,
  unlock,
} from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const TWO_EXCHANGES = {
  kind: "ok",
  body: [pool("bybit", "linear"), pool("binance"), pool("bybit", "spot")],
} as const;
const STRATEGY_ID = "5b0c7a52-6f43-4d6e-9c1c-0c2f3f3f2a11";

/** The two lists the tabs' rule reads besides the keys and the positions: nothing enabled, nothing held. */
const NOTHING_RUNNING: ExtraRoute = (url) => {
  if (url.includes("/api/strategies")) return Promise.resolve(jsonResponse([]));
  if (url.endsWith("/subscriptions/held")) return Promise.resolve(jsonResponse([]));
  return undefined;
};

function poolCalls(fetchMock: ReturnType<typeof stubApi>) {
  return fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/pools"));
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

describe("for a signed-in user who is not the admin", () => {
  it("draws the tabs, so a user keyed on two exchanges can switch between them", async () => {
    const notTheAdmin: ExtraRoute = (url) =>
      url.endsWith("/api/me")
        ? Promise.resolve(jsonResponse({ email: "a@example.com", is_admin: false, mode: "SIMULATION", dry_run_brake: false, ...SIGNED_UP }))
        : undefined;
    stubApi(HEALTH, [], TWO_EXCHANGES, {}, notTheAdmin);
    renderAt(<ExchangeTabs />);

    const bar = await screen.findByRole("navigation", { name: "Exchanges" });
    expect((await within(bar).findAllByRole("button")).map(drawnName)).toEqual(["Bybit", "Binance"]);
  });
});

describe("tabs only where something runs (owner decision 37)", () => {
  it("draws a tab for the exchange with a key and none for the one that only has pools", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES, {}, NOTHING_RUNNING, {}, { kind: "ok", body: [storedKey("binance")] });
    renderAt(<ExchangeTabs />);

    const bar = await screen.findByRole("navigation", { name: "Exchanges" });
    await waitFor(() => expect(within(bar).getAllByRole("button").map(drawnName)).toEqual(["Binance"]));
  });

  it("keeps both tabs while the held subscriptions have not answered", async () => {
    const holding: ExtraRoute = (url) =>
      url.endsWith("/subscriptions/held") ? new Promise<Response>(() => undefined) : NOTHING_RUNNING(url);
    stubApi(HEALTH, [], TWO_EXCHANGES, {}, holding, {}, { kind: "ok", body: [storedKey("binance")] });
    renderAt(<ExchangeTabs />);

    const bar = await screen.findByRole("navigation", { name: "Exchanges" });
    await waitFor(() => expect(within(bar).getAllByRole("button").map(drawnName)).toEqual(["Bybit", "Binance"]));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(within(bar).getAllByRole("button").map(drawnName)).toEqual(["Bybit", "Binance"]);
  });
});

describe("which routes show the tabs", () => {
  it.each([
    ["/", "Overview"],
    ["/strategies/authored", "My strategies"],
    [`/strategies/${STRATEGY_ID}`, "Strategy"],
  ])("shows one tab per distinct exchange on %s, in one bar", async (path, title) => {
    stubApi(HEALTH, [], TWO_EXCHANGES, {}, strategyRoute(STRATEGY_ID, "Strategy"));
    renderAt(<AppRoutes />, path);

    await screen.findByRole("heading", { level: 1, name: title });
    const bars = await screen.findAllByRole("navigation", { name: "Exchanges" });
    expect(bars).toHaveLength(1);
    for (const bar of bars) {
      expect(within(bar).getAllByRole("button").map(drawnName)).toEqual(["Bybit", "Binance"]);
    }
  });

  // Settings reads the pools itself since PR 13 (it needs them for the cards), so this no longer says it never asks.
  it("shows no tabs on /settings", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/settings");

    await screen.findByRole("heading", { level: 1, name: "My account" });
    await screen.findByText("Simulation forced");
    expect(screen.queryByRole("navigation", { name: "Exchanges" })).not.toBeInTheDocument();
  });

  it("shows no tabs on the not-found page", async () => {
    const fetchMock = stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/no/such/page");

    await screen.findByRole("heading", { level: 1, name: "Page not found" });
    expect(screen.queryByRole("navigation", { name: "Exchanges" })).not.toBeInTheDocument();
    expect(poolCalls(fetchMock)).toHaveLength(0);
  });

  it("shows no tabs while signed out, and never asks for pools", async () => {
    lock();
    const fetchMock = stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    await screen.findByRole("button", { name: "Sign in again" });
    expect(screen.queryByRole("navigation", { name: "Exchanges" })).not.toBeInTheDocument();
    expect(poolCalls(fetchMock)).toHaveLength(0);
  });

  it("drops the tabs when the settings link is followed", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");
    await screen.findAllByRole("navigation", { name: "Exchanges" });

    fireEvent.click(screen.getAllByRole("link", { name: /My account/ })[0] as HTMLElement);

    await screen.findByRole("heading", { level: 1, name: "My account" });
    expect(screen.queryByRole("navigation", { name: "Exchanges" })).not.toBeInTheDocument();
  });
});

describe("selection", () => {
  it("marks the first exchange as selected by default", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    const pressed = await screen.findAllByRole("button", { name: "Bybit", pressed: true });
    expect(pressed).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Binance", pressed: true })).not.toBeInTheDocument();
  });

  it("selects the clicked exchange and persists it under sm.exchange", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    const tabs = await screen.findAllByRole("button", { name: "Binance" });
    fireEvent.click(tabs[0] as HTMLElement);

    expect(await screen.findAllByRole("button", { name: "Binance", pressed: true })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Bybit", pressed: true })).not.toBeInTheDocument();
    const raw = window.localStorage.getItem("sm.exchange");
    expect(JSON.parse(raw as string).state.selected).toBe("binance");
  });

  it("keeps the selection when moving between scoped routes", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES, {}, NOTHING_RUNNING);
    renderAt(<AppRoutes />, "/");
    fireEvent.click((await screen.findAllByRole("button", { name: "Binance" }))[0] as HTMLElement);

    fireEvent.click(screen.getByRole("link", { name: "My strategies" }));

    expect(await screen.findAllByRole("button", { name: "Binance", pressed: true })).toHaveLength(1);
  });

  it("starts from a persisted exchange that is still an option", async () => {
    window.localStorage.setItem(
      "sm.exchange",
      JSON.stringify({ state: { selected: "binance" }, version: 0 }),
    );
    const { useExchangeStore } = await import("@/shared/scope/exchange-store");
    await useExchangeStore.persist.rehydrate();
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    expect(await screen.findAllByRole("button", { name: "Binance", pressed: true })).toHaveLength(1);
  });

  it("falls back to the first exchange when the persisted one is gone", async () => {
    window.localStorage.setItem(
      "sm.exchange",
      JSON.stringify({ state: { selected: "kraken" }, version: 0 }),
    );
    const { useExchangeStore } = await import("@/shared/scope/exchange-store");
    await useExchangeStore.persist.rehydrate();
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    expect(await screen.findAllByRole("button", { name: "Bybit", pressed: true })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Kraken" })).not.toBeInTheDocument();
  });
});

describe("pools loading and failure", () => {
  it("says it is loading, with no tab to click, while pools load", async () => {
    stubApi(HEALTH, [], { kind: "pending" });
    renderAt(<AppRoutes />, "/");

    const bars = await screen.findAllByRole("navigation", { name: "Exchanges" });
    for (const bar of bars) {
      expect(within(bar).getByRole("status")).toHaveTextContent(en.scope.loading);
      expect(within(bar).queryByRole("button")).not.toBeInTheDocument();
    }
  });

  it.each([
    ["a 500", { kind: "status", status: 500, body: { detail: "boom" } }],
    ["a network failure", { kind: "network-error" }],
    ["a body that is not a list", { kind: "ok", body: { items: [] } }],
  ] as const)("says the exchanges could not load on %s, never an empty bar", async (_label, stub) => {
    stubApi(HEALTH, [], stub);
    renderAt(<AppRoutes />, "/");

    const bars = await screen.findAllByRole("navigation", { name: "Exchanges" });
    for (const bar of bars) {
      expect(await within(bar).findByRole("alert")).toHaveTextContent(en.scope.error);
      expect(within(bar).queryByRole("button")).not.toBeInTheDocument();
    }
  });

  it("does not crash the shell when pools fail: navigation and the badge stay", async () => {
    stubApi(HEALTH, [], { kind: "status", status: 503, body: {} });
    renderAt(<AppRoutes />, "/");

    expect(await screen.findAllByRole("navigation", { name: "Sections" })).toHaveLength(1);
    expect(await screen.findByText("Simulation forced")).toBeInTheDocument();
  });

  it("renders no tab when the pool list is empty, without failing", async () => {
    stubApi(HEALTH, [], { kind: "ok", body: [] });
    renderAt(<AppRoutes />, "/");

    await screen.findByRole("heading", { level: 1, name: "Overview" });
    for (const bar of await screen.findAllByRole("navigation", { name: "Exchanges" })) {
      expect(within(bar).queryByRole("button")).not.toBeInTheDocument();
      expect(within(bar).queryByRole("alert")).not.toBeInTheDocument();
    }
  });
});

describe("layout contract", () => {
  it("puts the tabs in the row above the page: beside the tools from lg, in a full-width scrollable row of their own below it", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    await screen.findAllByRole("button", { name: "Bybit" });
    const bar = screen.getByRole("navigation", { name: "Exchanges" });
    const tools = screen.getByRole("group", { name: "Tools" });

    // One row holds both, the bar after the tools on a phone and before them from `lg`.
    expect(bar.parentElement).toBe(tools.parentElement);
    expect(bar).toHaveClass("order-3", "w-full", "lg:order-2", "lg:w-auto");
    expect(tools).toHaveClass("order-2", "lg:order-3");

    // The row scrolls sideways instead of wrapping or stretching the page.
    expect(bar).toHaveClass("overflow-x-auto", "min-w-0");
    expect(bar).not.toHaveClass("flex-wrap");
    // Below `lg` the tabs share the row's whole width, each the same, and never shrink under their
    // own name (design § E, decision 59). Every tab is 36 px tall, as tall as the mode badge and the
    // icon buttons beside it (owner, 2026-11-24).
    for (const tab of within(bar).getAllByRole("button")) {
      expect(tab).toHaveClass("flex-1", "min-w-fit", "lg:flex-none", "whitespace-nowrap", "border", "h-9");
      expect(tab).not.toHaveClass("shrink-0");
    }
  });

  it("marks the selected tab by its background alone: the rule's border on every tab, never the gain colour", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    await screen.findAllByRole("button", { name: "Bybit" });
    const selected = screen.getByRole("button", { name: "Bybit", pressed: true });
    const other = screen.getByRole("button", { name: "Binance", pressed: false });
    expect(selected).toHaveClass("border-rule", "bg-panel-2");
    expect(other).toHaveClass("border-rule", "bg-panel");
    for (const tab of [selected, other]) expect(tab.className).not.toMatch(/\bborder-gain\b/);
  });

  it("uses no hex colour or var() in any tab class", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    await screen.findAllByRole("button", { name: "Bybit" });
    for (const bar of screen.getAllByRole("navigation", { name: "Exchanges" })) {
      for (const node of [bar, ...within(bar).getAllByRole("button")]) {
        expect(node.className).not.toMatch(/#[0-9a-fA-F]{3,8}|var\(/);
      }
    }
  });
});

/** The tabs of a shell render, with the pools and the credentials a test names. */
function renderTabs(poolRows: unknown[], credentials: CredentialsStub) {
  const fetchMock = stubApi(HEALTH, [], { kind: "ok", body: poolRows }, {}, undefined, {}, credentials);
  renderAt(<AppRoutes />, "/");
  return fetchMock;
}

function credentialsOk(...rows: unknown[]): CredentialsStub {
  return { kind: "ok", body: rows };
}

function disabled(exchange: string) {
  return { ...pool(exchange), enabled: false };
}

/** The tabs' bar: one for every width (the same bar scrolls sideways on a phone). Kept as a list so the checks read as before. */
async function bothBars(): Promise<HTMLElement[]> {
  await screen.findAllByRole("button", { name: /Bybit/ });
  const bars = screen.getAllByRole("navigation", { name: "Exchanges" });
  expect(bars).toHaveLength(1);
  return bars;
}

/** Waits for a tab by its exact accessible name; a missing one fails as an assertion, not a query error. */
async function tabNamed(bar: HTMLElement, name: string): Promise<HTMLElement> {
  await waitFor(() => expect(within(bar).queryByRole("button", { name })).toBeInTheDocument());
  return within(bar).getByRole("button", { name });
}

/** A tab's name as it is drawn: its logotype's accessible name, or its text where it has no logotype (decision 77). */
function drawnName(element: Element): string {
  return element.querySelector('[role="img"]')?.getAttribute("aria-label") ?? element.textContent ?? "";
}

describe("a tab says nothing about the key (owner, 2026-11-24)", () => {
  // "La fila de la key, por ejemplo 'sin clave' que no se muestre ahí. A lo sumo se verá en la vista de gestion de API keys."
  it("draws the exchange's name alone, with a key that cannot trade and with no key at all", async () => {
    renderTabs(
      [pool("bybit"), pool("binance"), pool("okx")],
      credentialsOk(storedKey("bybit"), storedKey("binance", { trade_capable: false }), emptyKey("okx")),
    );

    for (const bar of await bothBars()) {
      // Give the credentials time to answer: a mark, if any were drawn, would be there by now.
      await new Promise((resolve) => setTimeout(resolve, 20));
      // Each accessible name is the exchange alone; a mark would have made it "Binance read-only" or "Okx no key".
      for (const name of ["Bybit", "Binance", "Okx"]) await tabNamed(bar, name);
      expect(within(bar).queryByText(/read-only|no key/)).not.toBeInTheDocument();
    }
  });
});

describe("the tabs' sizing (jsdom has no layout)", () => {
  const MIXED = [pool("bybit"), pool("binance"), pool("okx"), disabled("kraken")];
  const CREDENTIALS = credentialsOk(
    storedKey("bybit"),
    storedKey("binance", { trade_capable: false }),
    emptyKey("okx"),
  );

  it("gives every tab flex-1, min-w-fit and lg:flex-none, never shrink-0", async () => {
    renderTabs(MIXED, CREDENTIALS);

    for (const bar of await bothBars()) {
      await tabNamed(bar, "Kraken");
      for (const tab of within(bar).getAllByRole("button")) {
        expect(tab).toHaveClass("flex-1", "min-w-fit", "lg:flex-none", "whitespace-nowrap");
        expect(tab).not.toHaveClass("shrink-0");
      }
      // The row still scrolls sideways and never wraps.
      expect(bar).toHaveClass("overflow-x-auto");
      expect(bar).not.toHaveClass("flex-wrap");
    }
  });
});

describe("the exchange's logotype on its tab (owner decision 77)", () => {
  // Pionex never gets a tab (decision 37, amended), so its logotype is not drawn here.
  const THREE = [pool("bybit"), pool("binance"), pool("kraken")];
  const ALL_KEYED = credentialsOk(storedKey("bybit"), storedKey("binance"), storedKey("kraken"));

  it("draws each known exchange's logotype, named by its display name, and a capitalised name where there is none", async () => {
    renderTabs(THREE, ALL_KEYED);

    for (const bar of await bothBars()) {
      await tabNamed(bar, "Kraken");
      const tabs = within(bar).getAllByRole("button");
      expect(tabs.map((tab) => within(tab).queryByRole("img")?.getAttribute("aria-label") ?? tab.textContent)).toEqual([
        "Bybit",
        "Binance",
        "Kraken",
      ]);
    }
  });

  it("dims the logotype of every tab but the selected one", async () => {
    renderTabs(THREE, ALL_KEYED);

    for (const bar of await bothBars()) {
      await tabNamed(bar, "Kraken");
      const dimmed = within(bar)
        .getAllByRole("img")
        .map((image) => [image.getAttribute("aria-label"), image.classList.contains("opacity-55")]);
      expect(dimmed).toEqual([
        ["Bybit", false],
        ["Binance", true],
      ]);
    }
  });
});

describe("copy", () => {
  it("has the scope strings in English and Spanish", () => {
    for (const locale of [en, es]) {
      expect(locale.scope.exchanges).toBeTruthy();
      expect(locale.scope.loading).toBeTruthy();
      expect(locale.scope.error).toBeTruthy();
    }
    // "Exchanges" is the word Spanish-speaking traders use, so the label matches.
    expect(es.scope.loading).not.toBe(en.scope.loading);
    expect(es.scope.error).not.toBe(en.scope.error);
  });
});
