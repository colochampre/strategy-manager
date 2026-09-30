import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { lock, pool, renderAt, resetExchangeScope, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const TWO_EXCHANGES = {
  kind: "ok",
  body: [pool("bybit", "linear"), pool("binance"), pool("bybit", "spot")],
} as const;
const STRATEGY_ID = "5b0c7a52-6f43-4d6e-9c1c-0c2f3f3f2a11";

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

describe("which routes show the tabs", () => {
  it.each([
    ["/", "Overview"],
    ["/strategies", "Strategies"],
    [`/strategies/${STRATEGY_ID}`, "Strategy"],
  ])("shows one tab per distinct exchange on %s, in both surfaces", async (path, title) => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, path);

    await screen.findByRole("heading", { level: 1, name: title });
    const bars = await screen.findAllByRole("navigation", { name: "Exchanges" });
    expect(bars).toHaveLength(2);
    for (const bar of bars) {
      expect(within(bar).getAllByRole("button").map((tab) => tab.textContent)).toEqual([
        "bybit",
        "binance",
      ]);
    }
  });

  it("shows no tabs on /settings and never asks for pools there", async () => {
    const fetchMock = stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/settings");

    await screen.findByRole("heading", { level: 1, name: "Settings" });
    await screen.findByText("Dry run");
    expect(screen.queryByRole("navigation", { name: "Exchanges" })).not.toBeInTheDocument();
    expect(poolCalls(fetchMock)).toHaveLength(0);
  });

  it("shows no tabs on the not-found page", async () => {
    const fetchMock = stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/no/such/page");

    await screen.findByRole("heading", { level: 1, name: "Page not found" });
    expect(screen.queryByRole("navigation", { name: "Exchanges" })).not.toBeInTheDocument();
    expect(poolCalls(fetchMock)).toHaveLength(0);
  });

  it("shows no tabs while the token gate is locked, and never asks for pools", async () => {
    lock();
    const fetchMock = stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    await screen.findByRole("button", { name: "Unlock" });
    expect(screen.queryByRole("navigation", { name: "Exchanges" })).not.toBeInTheDocument();
    expect(poolCalls(fetchMock)).toHaveLength(0);
  });

  it("drops the tabs when the settings link is followed", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");
    await screen.findAllByRole("navigation", { name: "Exchanges" });

    fireEvent.click(screen.getAllByRole("link", { name: "Settings" })[0] as HTMLElement);

    await screen.findByRole("heading", { level: 1, name: "Settings" });
    expect(screen.queryByRole("navigation", { name: "Exchanges" })).not.toBeInTheDocument();
  });
});

describe("selection", () => {
  it("marks the first exchange as selected by default, in both surfaces", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    const pressed = await screen.findAllByRole("button", { name: "bybit", pressed: true });
    expect(pressed).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "binance", pressed: true })).not.toBeInTheDocument();
  });

  it("selects the clicked exchange and persists it under sm.exchange", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    const tabs = await screen.findAllByRole("button", { name: "binance" });
    fireEvent.click(tabs[0] as HTMLElement);

    expect(await screen.findAllByRole("button", { name: "binance", pressed: true })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "bybit", pressed: true })).not.toBeInTheDocument();
    const raw = window.localStorage.getItem("sm.exchange");
    expect(JSON.parse(raw as string).state.selected).toBe("binance");
  });

  it("keeps the selection when moving between scoped routes", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");
    fireEvent.click((await screen.findAllByRole("button", { name: "binance" }))[0] as HTMLElement);

    fireEvent.click(screen.getAllByRole("link", { name: "Strategies" })[0] as HTMLElement);

    await screen.findByRole("heading", { level: 1, name: "Strategies" });
    expect(await screen.findAllByRole("button", { name: "binance", pressed: true })).toHaveLength(2);
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

    expect(await screen.findAllByRole("button", { name: "binance", pressed: true })).toHaveLength(2);
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

    expect(await screen.findAllByRole("button", { name: "bybit", pressed: true })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "kraken" })).not.toBeInTheDocument();
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

    expect(await screen.findAllByRole("navigation", { name: "Sections" })).toHaveLength(2);
    expect(await screen.findByText("Dry run")).toBeInTheDocument();
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
  it("puts the tabs in the top bar on wide screens and in a scrollable row below it on narrow ones", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    await screen.findAllByRole("button", { name: "bybit" });
    const [wide, narrow] = screen.getAllByRole("navigation", { name: "Exchanges" });
    const header = screen.getByRole("banner");

    expect(wide).toHaveClass("hidden", "lg:flex");
    expect(narrow).toHaveClass("lg:hidden");
    expect(narrow).not.toHaveClass("hidden");

    // Both live in the header, and the narrow one is its LAST row.
    expect(header).toContainElement(wide as HTMLElement);
    expect(header).toContainElement(narrow as HTMLElement);
    expect(header.lastElementChild).toBe(narrow);
    expect(header.firstElementChild).not.toBe(narrow);

    // The row scrolls sideways instead of wrapping or stretching the page.
    for (const bar of [wide, narrow]) {
      expect(bar).toHaveClass("overflow-x-auto", "min-w-0");
      expect(bar).not.toHaveClass("flex-wrap");
    }
    for (const tab of within(narrow as HTMLElement).getAllByRole("button")) {
      expect(tab).toHaveClass("shrink-0", "whitespace-nowrap", "min-h-11");
    }
  });

  it("keeps the header out of the content's scroll: it never shrinks", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    await screen.findAllByRole("navigation", { name: "Exchanges" });
    expect(screen.getByRole("banner")).toHaveClass("shrink-0");
  });

  it("uses no hex colour or var() in any tab class", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    await screen.findAllByRole("button", { name: "bybit" });
    for (const bar of screen.getAllByRole("navigation", { name: "Exchanges" })) {
      for (const node of [bar, ...within(bar).getAllByRole("button")]) {
        expect(node.className).not.toMatch(/#[0-9a-fA-F]{3,8}|var\(/);
      }
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
