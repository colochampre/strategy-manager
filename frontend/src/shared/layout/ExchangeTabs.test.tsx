import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import {
  type CredentialsStub,
  emptyKey,
  lock,
  pool,
  renderAt,
  resetExchangeScope,
  storedKey,
  strategyRoute,
  stubApi,
  unlock,
} from "@/test/harness";

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
    stubApi(HEALTH, [], TWO_EXCHANGES, {}, strategyRoute(STRATEGY_ID, "Strategy"));
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

  // Settings reads the pools itself since PR 13 (it needs them for the cards), so this no longer says it never asks.
  it("shows no tabs on /settings", async () => {
    stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/settings");

    await screen.findByRole("heading", { level: 1, name: "Settings" });
    await screen.findByText("Dry run");
    expect(screen.queryByRole("navigation", { name: "Exchanges" })).not.toBeInTheDocument();
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
    // Below `lg` the tabs share the row's whole width, each the same, and never shrink under their
    // own name (design § E, decision 59); the height is on the inner span, 52 px on every tab.
    for (const tab of within(narrow as HTMLElement).getAllByRole("button")) {
      expect(tab).toHaveClass("flex-1", "min-w-fit", "lg:flex-none", "whitespace-nowrap");
      expect(tab).not.toHaveClass("shrink-0");
      expect(tab.firstElementChild).toHaveClass("min-h-13");
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

function credentialCalls(fetchMock: ReturnType<typeof stubApi>) {
  return fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/credentials"));
}

/** The two surfaces of the tabs: the bar from `lg` and the row below it on a phone. */
async function bothBars(): Promise<HTMLElement[]> {
  await screen.findAllByRole("button", { name: /bybit/ });
  const bars = screen.getAllByRole("navigation", { name: "Exchanges" });
  expect(bars).toHaveLength(2);
  return bars;
}

/** Waits for a tab by its exact accessible name; a missing one fails as an assertion, not a query error. */
async function tabNamed(bar: HTMLElement, name: string): Promise<HTMLElement> {
  await waitFor(() => expect(within(bar).queryByRole("button", { name })).toBeInTheDocument());
  return within(bar).getByRole("button", { name });
}

describe("the key mark of a tab (design § E), in both surfaces", () => {
  const BOTH_ON = [pool("bybit"), pool("binance")];
  const BINANCE_OFF = [pool("bybit"), disabled("binance")];

  it.each([
    [
      "a key that cannot trade",
      credentialsOk(storedKey("bybit"), storedKey("binance", { trade_capable: false })),
      BOTH_ON,
      "binance read-only",
      "read-only",
      "text-decision",
    ],
    [
      "no key and a pool on",
      credentialsOk(storedKey("bybit"), emptyKey("binance")),
      BOTH_ON,
      "binance no key",
      "no key",
      "text-decision",
    ],
    [
      "no key and a pool on, the exchange not listed at all",
      credentialsOk(storedKey("bybit")),
      BOTH_ON,
      "binance no key",
      "no key",
      "text-decision",
    ],
    [
      "a deleted key: no key and no pool on",
      credentialsOk(storedKey("bybit"), emptyKey("binance")),
      BINANCE_OFF,
      "binance no key",
      "no key",
      "text-ink-3",
    ],
    [
      "an exchange never keyed: not listed and no pool on",
      credentialsOk(storedKey("bybit")),
      BINANCE_OFF,
      "binance no key",
      "no key",
      "text-ink-3",
    ],
  ] as const)("%s", async (_label, credentials, poolRows, tabName, markText, tone) => {
    renderTabs([...poolRows], credentials);

    for (const bar of await bothBars()) {
      const tab = await tabNamed(bar, tabName);
      const mark = within(tab).getByText(markText);
      expect(mark).toHaveClass(tone);
      expect(mark).not.toHaveClass(tone === "text-decision" ? "text-ink-3" : "text-decision");
      // The exchange whose key trades is its name alone: no mark, nothing after the name.
      const plain = within(bar).getByRole("button", { name: "bybit" });
      expect(plain.textContent).toBe("bybit");
    }
  });

  it("gives a key that trades the name alone, accessible name `bybit`, beside a marked tab", async () => {
    renderTabs(BOTH_ON, credentialsOk(storedKey("bybit"), storedKey("binance", { trade_capable: false })));

    for (const bar of await bothBars()) {
      await tabNamed(bar, "binance read-only");
      expect(within(bar).queryByRole("button", { name: "bybit" })).toBeInTheDocument();
      expect(within(bar).getByRole("button", { name: "bybit" }).textContent).toBe("bybit");
    }
  });

  it.each([
    ["is still loading", { kind: "pending" }],
    ["answered 500", { kind: "status", status: 500, body: { detail: "boom" } }],
    ["could not be reached", { kind: "network-error" }],
    ["answered a body that is not a list of keys", { kind: "ok", body: { items: [] } }],
  ] as const)("draws no mark at all while the credentials read %s", async (_label, stub) => {
    // Neither exchange has a key that trades here, so any mark drawn would be a claim made on nothing.
    const fetchMock = renderTabs([pool("bybit"), pool("binance")], stub);

    await screen.findAllByRole("button", { name: "bybit" });
    await waitFor(() => expect(credentialCalls(fetchMock)).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 20));

    for (const bar of screen.getAllByRole("navigation", { name: "Exchanges" })) {
      expect(within(bar).getAllByRole("button").map((tab) => tab.textContent)).toEqual(["bybit", "binance"]);
      expect(bar.querySelector(".row-start-3")).toBeNull();
    }
  });
});

describe("the structure that keeps a tab's name at the same place (jsdom has no layout)", () => {
  const MIXED = [pool("bybit"), pool("binance"), pool("pionex"), disabled("kraken")];
  const CREDENTIALS = credentialsOk(
    storedKey("bybit"),
    storedKey("binance", { trade_capable: false }),
    emptyKey("pionex"),
  );
  const MARKED = new Map([
    ["binance", "read-only"],
    ["pionex", "no key"],
    ["kraken", "no key"],
  ]);

  it("gives every tab, marked or not, the same grid, one name in the middle row and a mark in the last", async () => {
    renderTabs(MIXED, CREDENTIALS);

    for (const bar of await bothBars()) {
      await tabNamed(bar, "kraken no key");
      const tabs = within(bar).getAllByRole("button");
      expect(tabs).toHaveLength(4);
      const nameClasses = new Set<string>();

      for (const tab of tabs) {
        const grid = tab.firstElementChild as HTMLElement;
        expect(grid.tagName).toBe("SPAN");
        expect(grid).toHaveClass(
          "grid",
          "min-h-13",
          "grid-rows-[minmax(0,1fr)_auto_minmax(0,1fr)]",
          "justify-items-center",
        );

        const names = Array.from(grid.children).filter((child) => child.classList.contains("row-start-2"));
        expect(names).toHaveLength(1);
        nameClasses.add(String(names[0]?.className));

        const exchange = names[0]?.textContent ?? "";
        const markText = MARKED.get(exchange);
        const marks = Array.from(grid.children).filter((child) => child.classList.contains("row-start-3"));
        if (markText === undefined) {
          // No mark: exactly one element in the grid, and the button's text is the name alone.
          expect(grid.children).toHaveLength(1);
          expect(marks).toHaveLength(0);
          expect(tab.textContent).toBe(exchange);
        } else {
          expect(grid.children).toHaveLength(2);
          expect(marks).toHaveLength(1);
          expect(marks[0]).toHaveTextContent(markText);
          // The accessible name is the name, a space and the mark; the space is a real text node.
          expect(tab.textContent).toBe(`${exchange} ${markText}`);
          expect(Array.from(grid.childNodes).some((node) => node.nodeType === 3 && node.textContent === " ")).toBe(
            true,
          );
        }
      }
      // One class list for the name in every tab.
      expect(nameClasses.size).toBe(1);
    }
  });

  it("gives every tab flex-1, min-w-fit and lg:flex-none, never shrink-0, in both surfaces", async () => {
    renderTabs(MIXED, CREDENTIALS);

    for (const bar of await bothBars()) {
      await tabNamed(bar, "kraken no key");
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

describe("the tabs read the credentials", () => {
  it("test_a_shell_render_asks_for_credentials_and_is_answered", async () => {
    const fetchMock = stubApi(HEALTH, [], TWO_EXCHANGES);
    renderAt(<AppRoutes />, "/");

    await screen.findAllByRole("button", { name: "bybit" });
    await waitFor(() => expect(credentialCalls(fetchMock).length).toBeGreaterThan(0));
    const index = fetchMock.mock.calls.findIndex(([url]) => String(url).endsWith("/credentials"));
    const answer = (await fetchMock.mock.results[index]?.value) as Response;
    expect(answer.ok).toBe(true);
    expect(fetchMock.unexpected).toEqual([]);
  });

  it("takes each mark from keyMark(keyState(...)) of the shared module and adds no amber class of its own", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const source = readFileSync(join(here, "ExchangeTabs.tsx"), "utf8");
    expect(source).toMatch(/keyMark\(\s*keyState\(/);
    expect(source).toContain('"@/shared/credentials/key-state"');
    expect(source).not.toMatch(/\b(?:bg|text|border|ring|outline|fill|stroke|divide)-decision\b/);
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
