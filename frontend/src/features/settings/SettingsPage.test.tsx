import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import { SettingsPage } from "@/features/settings/SettingsPage";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import {
  type CredentialsStub,
  type ExtraRoute,
  emptyKey,
  jsonResponse,
  lock,
  pool,
  renderAt,
  resetExchangeScope,
  storedKey,
  stubApi,
  unlock,
} from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const INTRO =
  "One key per exchange. Keys are encrypted on the server and never shown again; you only see the last four characters.";
const POOLS_LINE = "The pools could not be loaded, so an exchange without a key is not marked here.";
const AMBER = /\b(?:bg|text|border|ring|outline|fill|stroke|divide)-decision\b/;

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

function ok(...rows: unknown[]): CredentialsStub {
  return { kind: "ok", body: rows };
}

function disabled(exchange: string) {
  return { ...pool(exchange), enabled: false };
}

/** The page alone, on its own query client so a test can ask the cache to read again. */
function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/settings"]}>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return queryClient;
}

function stub(credentials: CredentialsStub, pools: unknown[] = [pool("bybit")], extra?: ExtraRoute) {
  return stubApi(HEALTH, [], { kind: "ok", body: pools }, {}, extra, {}, credentials);
}

/** Waits until a card is drawn; a missing one fails as an assertion. */
async function cardsDrawn(): Promise<HTMLElement[]> {
  await waitFor(() => expect(screen.queryAllByRole("article").length).toBeGreaterThan(0));
  return screen.getAllByRole("article");
}

/** A heading's name as it is drawn: the logotype's accessible name, or its text where it has none (decision 77). */
function headingName(heading: HTMLElement): string {
  return heading.querySelector('[role="img"]')?.getAttribute("aria-label") ?? heading.textContent ?? "";
}

function cardNames(): string[] {
  return screen.getAllByRole("heading", { level: 3 }).map(headingName);
}

function credentialCalls(fetchMock: ReturnType<typeof stubApi>) {
  return fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/credentials"));
}

describe("the page's structure", () => {
  it("keeps the h1 `Settings` and adds the h2 `Exchange keys` with its intro word for word", async () => {
    stub(ok(storedKey("bybit")));
    mountPage();

    expect(screen.queryByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 2, name: "Exchange keys" })).toBeInTheDocument();
    expect(screen.queryByText(INTRO)).toBeInTheDocument();
    await cardsDrawn();
  });

  it("puts the headings in order: h1, h2, then one h3 per exchange", async () => {
    stub(ok(storedKey("bybit")));
    mountPage();
    await cardsDrawn();

    const outline = screen.getAllByRole("heading").map((heading) => `${heading.tagName} ${headingName(heading)}`);
    expect(outline).toEqual(["H1 Settings", "H2 Exchange keys", "H3 Bybit"]);
  });

  it("draws the cards as a list, one item per exchange, each holding its article", async () => {
    stub(ok(storedKey("bybit")));
    mountPage();
    await cardsDrawn();

    const list = screen.queryByRole("list", { name: "Exchange keys" });
    expect(list).toBeInTheDocument();
    const items = within(list as HTMLElement).getAllByRole("listitem");
    const articles = screen.getAllByRole("article");
    // The tags of a card are a list too, so only the card's own items are counted.
    const own = items.filter((item) => item.parentElement === list);
    expect(own).toHaveLength(articles.length);
    for (const item of own) expect(within(item).getAllByRole("article")).toHaveLength(1);
  });

  it("puts no width cap of its own around a card: the shell's column is the only one", async () => {
    stub(ok(storedKey("bybit")));
    mountPage();
    const [card] = await cardsDrawn();

    // Strategies fills the shell's column (decision 38). A cap on this page makes
    // its cards end short of where the cards of Strategies end (decision 60).
    const capped: string[] = [];
    for (let node: HTMLElement | null | undefined = card; node != null; node = node.parentElement) {
      if (/(^|\s)max-w-/.test(node.className)) capped.push(node.className);
    }
    expect(capped).toEqual([]);
  });
});

describe("the list of exchanges", () => {
  it("test_no_exchange_tabs_lists_every_exchange: no exchange bar on Settings, and a card for every exchange with a key", async () => {
    stubApi(
      HEALTH,
      [],
      { kind: "ok", body: [pool("bybit"), pool("pionex", "spot")] },
      {},
      undefined,
      {},
      ok(storedKey("bybit"), storedKey("pionex")),
    );
    renderAt(<AppRoutes />, "/settings");

    await cardsDrawn();
    expect(screen.queryByRole("navigation", { name: "Exchanges" })).not.toBeInTheDocument();
    expect(cardNames()).toEqual(["Bybit", "Pionex"]);
  });

  it("gives no card to a served exchange with no key and no pool (decision 80)", async () => {
    stub(ok(storedKey("bybit")), [pool("bybit")]);
    mountPage();
    await cardsDrawn();

    expect(cardNames()).toEqual(["Bybit"]);
    expect(screen.queryByRole("article", { name: "Binance" })).not.toBeInTheDocument();
  });

  it("gives no card to an exchange whose only row is EMPTY and whose pool is off", async () => {
    stub(ok(storedKey("bybit"), emptyKey("binance")), [pool("bybit"), disabled("binance")]);
    mountPage();
    await cardsDrawn();

    expect(cardNames()).toEqual(["Bybit"]);
  });

  it("shows a stored key of an exchange nothing else lists, with no button", async () => {
    stub(ok(storedKey("bybit"), storedKey("kraken", { last4: "AB12" })), [pool("bybit")]);
    mountPage();
    await cardsDrawn();

    expect(cardNames()).toEqual(["Bybit", "Kraken"]);
    const kraken = screen.getByRole("article", { name: "Kraken" });
    expect(within(kraken).queryByText("key ending in AB12")).toBeInTheDocument();
    expect(within(kraken).queryAllByRole("button")).toEqual([]);
  });

  it("lists the served exchanges first in the file's order, then the others of the credentials by name, then the pool-only ones by name", async () => {
    stub(ok(storedKey("zeta"), storedKey("binance"), storedKey("bybit"), storedKey("alpha")), [
      pool("pionex"),
      pool("mexc"),
      pool("zeta"),
      pool("bybit"),
    ]);
    mountPage();
    await cardsDrawn();

    expect(cardNames()).toEqual(["Bybit", "Binance", "Alpha", "Zeta", "Mexc", "Pionex"]);
  });

  it("marks the degraded exchange amber and leaves an exchange whose pool is off neutral", async () => {
    stub(ok(storedKey("bybit")), [pool("bybit"), pool("binance")]);
    mountPage();
    await cardsDrawn();
    expect(screen.getByRole("article", { name: "Binance" })).toHaveClass("border-decision");
    expect(screen.getByRole("article", { name: "Bybit" })).toHaveClass("border-rule");
  });

  it("keeps the degraded card of an exchange with no key and an enabled pool, with its `Add key` (decision 80 Q2)", async () => {
    stub(ok(storedKey("bybit"), emptyKey("binance")), [pool("bybit"), pool("binance")]);
    mountPage();
    await cardsDrawn();

    const binance = screen.getByRole("article", { name: "Binance" });
    expect(binance.outerHTML).toMatch(AMBER);
    expect(within(binance).queryByRole("button", { name: "Add key Binance" })).toBeInTheDocument();
  });
});

describe("the page's own states", () => {
  it("says it is loading and draws no card while the keys are not known", async () => {
    stub({ kind: "pending" });
    mountPage();

    // Task 13.5.10 (R12): the page now also holds a hidden status region, so the loading line is found by its text.
    await waitFor(() => expect(screen.queryByText("Loading exchange keys…")).toBeInTheDocument());
    expect(screen.getByText("Loading exchange keys…")).toHaveAttribute("role", "status");
    expect(screen.queryAllByRole("article")).toEqual([]);
    expect(screen.queryByRole("heading", { level: 2, name: "Exchange keys" })).toBeInTheDocument();
  });

  it.each([
    ["answers 500", { kind: "status", status: 500, body: { detail: "boom" } }],
    ["cannot be reached", { kind: "network-error" }],
    ["answers a body that is not a list", { kind: "ok", body: { items: [] } }],
  ] as const)("shows the error and `Try again`, and no card, when the first read %s", async (_label, credentials) => {
    stub(credentials);
    mountPage();

    await waitFor(() => expect(screen.queryByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("Exchange keys could not be loaded.");
    expect(screen.queryByRole("button", { name: "Try again" })).toBeInTheDocument();
    // A card drawn from the file alone would say "No key stored" about a key the panel could not read.
    expect(screen.queryAllByRole("article")).toEqual([]);
    expect(screen.queryByText(/No key stored/)).not.toBeInTheDocument();
  });

  it("reads again on `Try again`, and draws the cards when the read works", async () => {
    let fail = true;
    const extra: ExtraRoute = (url, init) => {
      if (url.endsWith("/credentials") && (init?.method ?? "GET") === "GET") {
        return Promise.resolve(fail ? jsonResponse({ detail: "boom" }, 500) : jsonResponse([storedKey("bybit")]));
      }
      return undefined;
    };
    const fetchMock = stub({ kind: "pending" }, [pool("bybit")], extra);
    mountPage();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Try again" })).toBeInTheDocument());
    expect(credentialCalls(fetchMock)).toHaveLength(1);

    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    await cardsDrawn();
    expect(credentialCalls(fetchMock)).toHaveLength(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps the cards under a line that says the list may be out of date when a later read fails, and reads again on `Try again`", async () => {
    let fail = false;
    const extra: ExtraRoute = (url, init) => {
      if (url.endsWith("/credentials") && (init?.method ?? "GET") === "GET") {
        return Promise.resolve(fail ? jsonResponse({ detail: "boom" }, 500) : jsonResponse([storedKey("bybit")]));
      }
      return undefined;
    };
    stub({ kind: "pending" }, [pool("bybit"), pool("binance")], extra);
    const queryClient = mountPage();
    await cardsDrawn();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    fail = true;
    await act(() => queryClient.refetchQueries({ queryKey: ["credentials"] }));

    await waitFor(() => expect(screen.queryByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("This list could not be refreshed and may be out of date.");
    expect(screen.queryAllByRole("article")).toHaveLength(2);
    expect(screen.queryByText("key ending in 1234")).toBeInTheDocument();
    expect(screen.queryByText("Exchange keys could not be loaded.")).not.toBeInTheDocument();

    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(screen.queryAllByRole("article")).toHaveLength(2);
  });

  it("draws the cards when the pools failed, marks no exchange amber for lack of a key, and says why in one line", async () => {
    stubApi(HEALTH, [], { kind: "status", status: 500, body: { detail: "boom" } }, {}, undefined, {}, ok(storedKey("bybit")));
    mountPage();
    await cardsDrawn();

    await waitFor(() => expect(screen.queryByText(POOLS_LINE)).toBeInTheDocument());
    expect(screen.queryAllByText(POOLS_LINE)).toHaveLength(1);
    // Not known to be degraded, so Binance, which has no key, has no card at all (decision 80).
    expect(cardNames()).toEqual(["Bybit"]);
    expect(screen.getAllByRole("article").every((card) => !AMBER.test(card.outerHTML))).toBe(true);
  });

  it("does not show the pools line while the pools are fine", async () => {
    stub(ok(storedKey("bybit")));
    mountPage();
    await cardsDrawn();
    expect(screen.queryByText(POOLS_LINE)).not.toBeInTheDocument();
  });

  it("test_a_last4_that_is_not_four_characters_is_refused_and_never_rendered", async () => {
    stub(ok(storedKey("bybit", { last4: "123456789012" })));
    mountPage();

    await waitFor(() => expect(screen.queryByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("Exchange keys could not be loaded.");
    expect(screen.queryAllByRole("article")).toEqual([]);
    expect(document.body.textContent).not.toContain("123456789012");
    expect(document.body.textContent).not.toContain("9012");
    expect(document.body.innerHTML).not.toContain("123456789012");
  });
});

describe("what the page reads", () => {
  it("reads exactly GET /credentials and GET /pools, and no request is unexpected", async () => {
    const fetchMock = stub(ok(storedKey("bybit")));
    mountPage();
    await cardsDrawn();
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/pools"))).toBe(true));

    const requests = fetchMock.mock.calls.map(
      ([url, init]) => `${init?.method ?? "GET"} ${String(url).replace(/^.*\/api/, "")}`,
    );
    expect([...new Set(requests)].sort()).toEqual(["GET /credentials", "GET /pools"]);
    expect(fetchMock.unexpected).toEqual([]);
  });
});

describe("the card and the tab agree", () => {
  const SHARED = "@/shared/credentials/key-state";

  it("takes the state and the mark of the card and of the tab from the same module", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const card = readFileSync(join(here, "ExchangeKeyCard.tsx"), "utf8");
    const tabs = readFileSync(join(here, "..", "..", "shared", "layout", "ExchangeTabs.tsx"), "utf8");
    const page = readFileSync(join(here, "SettingsPage.tsx"), "utf8");
    for (const [name, source] of [
      ["ExchangeKeyCard.tsx", card],
      ["ExchangeTabs.tsx", tabs],
    ] as const) {
      expect(source, name).toContain(`"${SHARED}"`);
      expect(source, name).toMatch(/keyState\(/);
      expect(source, name).toMatch(/keyMark\(/);
    }
    expect(page).toContain(`"${SHARED}"`);
    expect(page).toMatch(/poolOn\(/);
    expect(page).toMatch(/exchangeList\(/);
  });

  it("says the same word for an exchange on its tab and on its card", async () => {
    const pools = [pool("bybit"), pool("binance"), pool("pionex", "spot"), disabled("kraken")];
    const credentials = ok(storedKey("bybit"), storedKey("binance", { trade_capable: false }), emptyKey("pionex"));
    stubApi(HEALTH, [], { kind: "ok", body: pools }, {}, undefined, {}, credentials);

    const wordsOnTabs = new Map<string, string>();
    const view = renderAt(<AppRoutes />, "/");
    await waitFor(() => expect(screen.queryAllByRole("button", { name: "Kraken no key" }).length).toBeGreaterThan(0));
    for (const tab of within(screen.getAllByRole("navigation", { name: "Exchanges" })[0] as HTMLElement).getAllByRole("button")) {
      // The tab's name is its logotype's accessible name, or its text where it has none (owner decision 77).
      const nameRow = tab.querySelector(".row-start-2");
      const name = nameRow?.querySelector('[role="img"]')?.getAttribute("aria-label") ?? nameRow?.textContent ?? "";
      wordsOnTabs.set(name, tab.querySelector(".row-start-3")?.textContent?.trim() ?? "");
    }
    view.unmount();

    renderAt(<AppRoutes />, "/settings");
    await cardsDrawn();
    await waitFor(() => expect(screen.queryByRole("article", { name: "Pionex" })?.textContent).toContain("no key"));
    for (const [exchange, word] of wordsOnTabs) {
      const card = screen.queryByRole("article", { name: exchange });
      // Kraken has no key and its pool is off: its tab says so, and it has no card (decision 80).
      if (exchange === "Kraken") {
        expect(card, exchange).toBeNull();
        continue;
      }
      expect(card, exchange).not.toBeNull();
      if (word === "") {
        expect(card?.textContent, exchange).not.toMatch(/read-only|no key/);
      } else {
        expect(card?.textContent, exchange).toContain(word);
      }
    }
    expect([...wordsOnTabs]).toEqual([
      ["Bybit", ""],
      ["Binance", "read-only"],
      ["Pionex", "no key"],
      ["Kraken", "no key"],
    ]);
  });
});

/** A card's toggle, "Add key" or "Replace key" with the exchange after it. */
function toggleOf(name: string): HTMLElement {
  const button = within(screen.getByRole("article", { name })).queryByRole("button", { name: /^(Add|Replace) key/ });
  expect(button, `the toggle of ${name}`).toBeInTheDocument();
  return button as HTMLElement;
}

/** An element that must be there: a missing one fails here as an assertion, not as a query error. */
function found<T extends HTMLElement>(element: T | null, label: string): T {
  expect(element, label).toBeInTheDocument();
  return element as T;
}

function formsOpen(): HTMLElement[] {
  return screen.queryAllByRole("heading", { level: 4 });
}

describe("the toggles and the open form (task 13.5.8)", () => {
  it("names the buttons with their exchange: `Replace key Bybit` and `Add key Binance`, not the same name twice", async () => {
    stub(ok(storedKey("bybit")), [pool("bybit"), pool("binance")]);
    mountPage();
    await cardsDrawn();

    const names = screen.getAllByRole("button").map((button) => button.getAttribute("aria-labelledby") === null ? "" : button.textContent);
    expect(names.filter((name) => name !== "")).toEqual(["Replace key", "Add key"]);
    expect(screen.queryByRole("button", { name: "Replace key Bybit" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add key Binance" })).toBeInTheDocument();
  });

  it("draws no button on a card that is not served", async () => {
    stub(ok(storedKey("bybit"), storedKey("kraken", { last4: "AB12" })), [pool("bybit")]);
    mountPage();
    await cardsDrawn();

    expect(within(screen.getByRole("article", { name: "Kraken" })).queryAllByRole("button")).toEqual([]);
  });

  it("test_one_form_at_a_time: opening another card's form closes and unmounts the open one", async () => {
    stub(ok(storedKey("bybit")), [pool("bybit"), pool("binance")]);
    mountPage();
    await cardsDrawn();

    fireEvent.click(toggleOf("Bybit"));
    expect(formsOpen().map((heading) => heading.textContent)).toEqual(["Replace the Bybit key"]);
    expect(toggleOf("Bybit")).toHaveAttribute("aria-expanded", "true");
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "FAKE-typed-text" } });

    fireEvent.click(toggleOf("Binance"));

    expect(formsOpen().map((heading) => heading.textContent)).toEqual(["Add a Binance key"]);
    expect(toggleOf("Bybit")).toHaveAttribute("aria-expanded", "false");
    expect(toggleOf("Binance")).toHaveAttribute("aria-expanded", "true");
    expect(within(screen.getByRole("article", { name: "Bybit" })).queryByRole("region")).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("FAKE-typed-text");
    expect((screen.getByLabelText("API key") as HTMLInputElement).value).toBe("");
  });

  it("points aria-controls at the form it opened", async () => {
    stub(ok(storedKey("bybit")));
    mountPage();
    await cardsDrawn();

    fireEvent.click(toggleOf("Bybit"));

    const section = screen.queryByRole("region", { name: "Replace the Bybit key" });
    expect(section).toBeInTheDocument();
    expect(toggleOf("Bybit")).toHaveAttribute("aria-controls", (section as HTMLElement).id);
  });

  it("test_the_opening_button_closes_its_own_form: and the focus returns to that button", async () => {
    stub(ok(storedKey("bybit")));
    mountPage();
    await cardsDrawn();
    fireEvent.click(toggleOf("Bybit"));
    expect(formsOpen()).toHaveLength(1);

    fireEvent.click(toggleOf("Bybit"));

    await waitFor(() => expect(formsOpen()).toEqual([]));
    expect(toggleOf("Bybit")).toHaveAttribute("aria-expanded", "false");
    expect(toggleOf("Bybit")).toHaveFocus();
  });

  it("test_closing_returns_the_focus_to_the_toggle", async () => {
    stub(ok(storedKey("bybit")), [pool("bybit"), pool("binance")]);
    mountPage();
    await cardsDrawn();
    fireEvent.click(toggleOf("Binance"));
    expect(screen.getByLabelText("API key")).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => expect(formsOpen()).toEqual([]));
    expect(toggleOf("Binance")).toHaveFocus();
  });

  it("disables every button of the page while any save is in flight", async () => {
    const pending = new Promise<Response>(() => undefined);
    const extra: ExtraRoute = (url, init) =>
      url.endsWith("/credentials/bybit") && init?.method === "PUT" ? pending : undefined;
    const fetchMock = stub(ok(storedKey("bybit")), [pool("bybit")], extra);
    mountPage();
    await cardsDrawn();
    fireEvent.click(toggleOf("Bybit"));
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "FAKE-key-0001" } });
    fireEvent.change(screen.getByLabelText("API secret"), { target: { value: "FAKE-secret-0002" } });

    fireEvent.click(screen.getByRole("button", { name: "Check and save" }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(true));
    const buttons = screen.getAllByRole("button");
    expect(buttons.length).toBeGreaterThanOrEqual(4);
    for (const button of buttons) expect(button, button.outerHTML).toBeDisabled();
  });
});

// ---- The end of a save that worked (design § F, decision 57; task 13.5.10) ----

const KEY_VALUE = "FAKE-key-0001";
const SECRET_VALUE = "FAKE-secret-0002";
const OLD_LAST4 = "1234";
const NEW_LAST4 = "7Q2d";
const SAVED_NOTICE = `Key ending in ${NEW_LAST4} saved.`;
const PENDING_NOTICE = `${SAVED_NOTICE} The rest of this card appears when the list has been read again.`;
/** The notice of a save, with or without its four characters; a refusal's "Nothing was saved." is not one. */
const SAVED_NOTICE_PATTERN = /^Key (ending in \w+ )?saved\./;
const STALE_LINE ="This list could not be refreshed and may be out of date.";
const READ_ONLY_BYBIT =
  "This key cannot trade. In live mode, opening signals for Bybit are refused until you add a key that can trade futures.";
const WITHDRAWALS_LABEL = "I confirmed in Binance that this key has withdrawals disabled";
const FUTURES_LABEL = "I confirmed in Binance that this key has Enable Futures";

function savedAnswer(exchange: string, overrides: Record<string, unknown> = {}) {
  return { exchange, last4: NEW_LAST4, warnings: [], facts: { trade_capable: true }, ...overrides };
}

type Reread = "ok" | "pending" | "fail" | "same";

interface SaveSetup {
  /** The list before the save. */
  credentials: unknown[];
  /** The list the re-read after the save returns (`ok`). */
  after?: unknown[];
  reread?: Reread;
  /** What the `PUT` answers; the exchange is its argument. */
  respond?: (exchange: string) => Promise<Response>;
  pools?: unknown[];
  /** Render the whole app (so the tabs exist) instead of the page alone. */
  shell?: boolean;
}

/** The page with a save wired: the `PUT` answered by the test and the re-read after it by `reread`. */
function savePage({
  credentials,
  after = credentials,
  reread = "ok",
  respond = (exchange) => Promise.resolve(jsonResponse(savedAnswer(exchange))),
  pools = [pool("bybit")],
  shell = false,
}: SaveSetup) {
  const state = { saved: false, reread };
  const extra: ExtraRoute = (url, init) => {
    const put = /\/credentials\/(\w+)$/.exec(url);
    if (put !== null && init?.method === "PUT") {
      state.saved = true;
      return respond(put[1] as string);
    }
    if (state.saved && url.endsWith("/credentials") && (init?.method ?? "GET") === "GET") {
      switch (state.reread) {
        case "pending":
          return new Promise<Response>(() => undefined);
        case "fail":
          return Promise.resolve(jsonResponse({ detail: "boom" }, 500));
        case "same":
          return Promise.resolve(jsonResponse(credentials));
        case "ok":
          return Promise.resolve(jsonResponse(after));
      }
    }
    return undefined;
  };
  const fetchMock = stub(ok(...credentials), pools, extra);
  if (shell) renderAt(<AppRoutes />, "/settings");
  else mountPage();
  return { fetchMock, state };
}

/** Opens a card's form, types both fields, ticks every box and presses the button. */
async function submitFor(name: string) {
  fireEvent.click(toggleOf(name));
  fireEvent.change(screen.getByLabelText("API key"), { target: { value: KEY_VALUE } });
  fireEvent.change(screen.getByLabelText("API secret"), { target: { value: SECRET_VALUE } });
  if (name === "Binance") {
    fireEvent.click(screen.getByLabelText(WITHDRAWALS_LABEL));
    fireEvent.click(screen.getByLabelText(FUTURES_LABEL));
  }
  fireEvent.click(screen.getByRole("button", { name: "Check and save" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Checking…" })).not.toBeInTheDocument());
}

/** Every string under a key of a locale, with its path, whatever the depth. */
function flatten(value: unknown, path = ""): [string, string][] {
  if (typeof value === "string") return [[path, value]];
  if (typeof value !== "object" || value === null) return [];
  return Object.entries(value).flatMap(([key, child]) => flatten(child, path === "" ? key : `${path}.${key}`));
}

/** None of the English texts of Settings (those that differ from their Spanish and hold no placeholder) is on screen. */
function expectNoEnglishSettingsText() {
  const spanish = new Map(flatten(es.settings));
  const text = document.body.textContent ?? "";
  let checked = 0;
  for (const [path, value] of flatten(en.settings)) {
    if (value.includes("{{") || spanish.get(path) === value) continue;
    expect(text, path).not.toContain(value);
    checked += 1;
  }
  expect(checked).toBeGreaterThan(25);
}

const noteIn = (card: HTMLElement, text: string) => within(card).queryByText(text);
const bybitCard = () => screen.getByRole("article", { name: "Bybit" });
const statusRegion = () => screen.queryAllByRole("status");

describe("the end of a save that worked (task 13.5.10)", () => {
  it("test_the_form_closes_on_the_answer", async () => {
    savePage({ credentials: [storedKey("bybit", { last4: OLD_LAST4 })], reread: "pending" });
    await cardsDrawn();

    await submitFor("Bybit");

    await waitFor(() => expect(formsOpen()).toEqual([]));
    expect(screen.queryByLabelText("API key")).not.toBeInTheDocument();
  });

  it("test_until_the_list_is_read_again_the_card_is_drawn_from_the_answer", async () => {
    savePage({ credentials: [storedKey("bybit", { last4: OLD_LAST4 })], reread: "pending" });
    await cardsDrawn();

    await submitFor("Bybit");

    await waitFor(() => expect(noteIn(bybitCard(), PENDING_NOTICE)).toBeInTheDocument());
    const card = bybitCard();
    // The key line is the SAVED key's hint, with no date; the old key is nowhere.
    expect(within(card).queryByText(`key ending in ${NEW_LAST4}`)).toBeInTheDocument();
    expect(card.textContent).toContain(NEW_LAST4);
    expect(card.textContent).not.toContain(OLD_LAST4);
    expect(document.body.textContent).not.toContain(OLD_LAST4);
    expect(card.textContent).not.toMatch(/checked|not validated/);
    // The answer said the key trades: no tag at all, and no state of the list is claimed.
    expect(within(card).queryByRole("list", { name: "What is known about this key" })).not.toBeInTheDocument();
    expect(card).toHaveClass("border-rule");
    expect(within(card).queryByRole("button", { name: /^Replace key/ })).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /^Delete key/ })).not.toBeInTheDocument();
  });

  it("draws the only tag the answer has, `read-only`, while the list is behind", async () => {
    savePage({
      credentials: [storedKey("bybit", { last4: OLD_LAST4 })],
      reread: "pending",
      respond: () => Promise.resolve(jsonResponse(savedAnswer("bybit", { warnings: ["READ_ONLY_KEY"] }))),
    });
    await cardsDrawn();

    await submitFor("Bybit");

    await waitFor(() => expect(noteIn(bybitCard(), PENDING_NOTICE)).toBeInTheDocument());
    const tags = within(within(bybitCard()).getByRole("list", { name: "What is known about this key" })).getAllByRole("listitem");
    expect(tags.map((tag) => tag.textContent)).toEqual(["read-only"]);
    expect(bybitCard().textContent).not.toContain(OLD_LAST4);
  });

  it("test_once_the_list_is_read_the_card_is_the_lists_with_the_notice", async () => {
    savePage({
      credentials: [storedKey("bybit", { last4: OLD_LAST4 })],
      after: [storedKey("bybit", { last4: NEW_LAST4, validated_at: "2026-10-09T09:30:00Z" })],
    });
    await cardsDrawn();

    await submitFor("Bybit");

    await waitFor(() => expect(within(bybitCard()).queryByText(`checked Oct 9, 2026`)).toBeInTheDocument());
    const card = bybitCard();
    const notice = found(noteIn(card, SAVED_NOTICE), "the notice");
    // A plain paragraph in ink-2, the first line of the facts, not a live region.
    expect(notice.tagName).toBe("P");
    expect(notice).toHaveClass("text-ink-2");
    expect(notice.closest("[role='status'], [aria-live]")).toBeNull();
    expect(notice.parentElement?.firstElementChild).toBe(notice);
    expect(noteIn(card, PENDING_NOTICE)).not.toBeInTheDocument();
    expect(card.textContent).not.toContain(OLD_LAST4);
  });

  it("test_an_identical_list_read_again_still_ends_the_pending_view", async () => {
    // The list read after the save is exactly the list held before it (dataUpdatedAt moves all the same, design § N).
    savePage({
      credentials: [storedKey("bybit", { last4: NEW_LAST4 })],
      reread: "same",
      respond: () => Promise.resolve(jsonResponse(savedAnswer("bybit"))),
    });
    await cardsDrawn();

    await submitFor("Bybit");

    await waitFor(() => expect(noteIn(bybitCard(), SAVED_NOTICE)).toBeInTheDocument());
    expect(noteIn(bybitCard(), PENDING_NOTICE)).not.toBeInTheDocument();
    expect(within(bybitCard()).queryByRole("list", { name: "What is known about this key" })).toBeInTheDocument();
  });

  it("test_a_failed_reread_keeps_the_pending_view_and_shows_the_stale_line", async () => {
    const { state } = savePage({ credentials: [storedKey("bybit", { last4: OLD_LAST4 })], reread: "fail" });
    await cardsDrawn();

    await submitFor("Bybit");

    await waitFor(() => expect(screen.queryByText(STALE_LINE)).toBeInTheDocument());
    expect(noteIn(bybitCard(), PENDING_NOTICE)).toBeInTheDocument();
    expect(bybitCard().textContent).not.toContain(OLD_LAST4);
    expect(screen.queryByRole("button", { name: "Try again" })).toBeInTheDocument();

    state.reread = "ok";
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() => expect(noteIn(bybitCard(), PENDING_NOTICE)).not.toBeInTheDocument());
    expect(screen.queryByText(STALE_LINE)).not.toBeInTheDocument();
  });

  it("test_a_read_only_key_is_a_state_of_the_card: from the answer before the list, from the list after, and on the tab", async () => {
    savePage({
      shell: true,
      credentials: [storedKey("bybit", { last4: OLD_LAST4 })],
      after: [storedKey("bybit", { last4: NEW_LAST4, trade_capable: false })],
      reread: "pending",
      respond: () => Promise.resolve(jsonResponse(savedAnswer("bybit", { warnings: ["READ_ONLY_KEY"] }))),
    });
    await cardsDrawn();
    await submitFor("Bybit");

    // Before the list is read: amber tag, amber border and the sentence, all from the answer.
    await waitFor(() => expect(noteIn(bybitCard(), PENDING_NOTICE)).toBeInTheDocument());
    const card = bybitCard();
    expect(card).toHaveClass("border-decision");
    expect(within(card).queryByText("read-only")).toHaveClass("text-decision");
    expect(within(card).queryByText(READ_ONLY_BYBIT)).toHaveClass("text-decision");
  });

  it("test_a_read_only_key_is_a_state_of_the_card: the list says so afterwards, and the tab shows `read-only`", async () => {
    savePage({
      shell: true,
      credentials: [storedKey("bybit", { last4: OLD_LAST4 })],
      after: [storedKey("bybit", { last4: NEW_LAST4, trade_capable: false })],
      respond: () => Promise.resolve(jsonResponse(savedAnswer("bybit", { warnings: ["READ_ONLY_KEY"] }))),
    });
    await cardsDrawn();
    await submitFor("Bybit");

    await waitFor(() => expect(noteIn(bybitCard(), SAVED_NOTICE)).toBeInTheDocument());
    expect(bybitCard()).toHaveClass("border-decision");
    expect(within(bybitCard()).queryByText(READ_ONLY_BYBIT)).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("link", { name: "Overview" })[0] as HTMLElement);
    await screen.findByRole("heading", { level: 1, name: "Overview" });
    for (const bar of await screen.findAllByRole("navigation", { name: "Exchanges" })) {
      await waitFor(() => expect(within(bar).queryByRole("button", { name: "Bybit read-only" })).toBeInTheDocument());
    }
  });

  it.each([
    ["an answer with no last4", savedAnswer("bybit", { last4: undefined }), false],
    ["a last4 that is not four characters", savedAnswer("bybit", { last4: "FAKE-WHOLE-KEY-VALUE" }), false],
    ["a last4 that is not a string", savedAnswer("bybit", { last4: 1234 }), false],
  ])("says `Key saved.` for %s, and draws no hint of a key the panel was not told", async (_label, body, readOnly) => {
    savePage({
      credentials: [storedKey("bybit", { last4: OLD_LAST4 })],
      reread: "pending",
      respond: () => Promise.resolve(jsonResponse(body)),
    });
    await cardsDrawn();

    await submitFor("Bybit");

    await waitFor(() => expect(noteIn(bybitCard(), "Key saved. The rest of this card appears when the list has been read again.")).toBeInTheDocument());
    expect(bybitCard().textContent).not.toContain(OLD_LAST4);
    expect(bybitCard().textContent).not.toContain("FAKE-WHOLE-KEY-VALUE");
    expect(bybitCard().className.includes("border-decision")).toBe(readOnly);
    expect(statusRegion().map((region) => region.textContent)).toEqual(["Key saved."]);
  });

  it("does not take a 200 whose body cannot be read for a save: the form stays open and says it is not known (task 13.2.14b)", async () => {
    savePage({
      credentials: [storedKey("bybit", { last4: OLD_LAST4 })],
      respond: () =>
        Promise.resolve({ ok: true, status: 200, json: () => Promise.reject(new SyntaxError("not json")) } as Response),
    });
    await cardsDrawn();

    await submitFor("Bybit");

    await waitFor(() => expect(screen.queryByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("(status 200)");
    expect(screen.getByRole("alert")).toHaveTextContent("not known whether the key was saved");
    expect(formsOpen()).toHaveLength(1);
    expect(screen.queryByText(SAVED_NOTICE_PATTERN)).not.toBeInTheDocument();
  });

  it("test_the_focus_goes_to_the_toggle: the same element, reading `Replace key` also after a FIRST key", async () => {
    savePage({ credentials: [storedKey("bybit")], reread: "pending", pools: [pool("bybit"), pool("binance")] });
    await cardsDrawn();
    const before = toggleOf("Binance");
    expect(before).toHaveTextContent("Add key");

    await submitFor("Binance");

    await waitFor(() => expect(formsOpen()).toEqual([]));
    const after = toggleOf("Binance");
    expect(after).toBe(before);
    expect(after).toHaveTextContent("Replace key");
    expect(after).toHaveAccessibleName("Replace key Binance");
    expect(document.activeElement).toBe(after);
  });

  it("moves the focus to the toggle after a replace too", async () => {
    savePage({ credentials: [storedKey("bybit", { last4: OLD_LAST4 })] });
    await cardsDrawn();
    const before = toggleOf("Bybit");

    await submitFor("Bybit");

    await waitFor(() => expect(formsOpen()).toEqual([]));
    expect(document.activeElement).toBe(before);
  });

  it("test_the_status_region_tells_a_screen_reader", async () => {
    savePage({ credentials: [storedKey("bybit", { last4: OLD_LAST4 })], reread: "pending" });
    await cardsDrawn();
    // Always in the document and hidden from sight, empty until a save.
    expect(statusRegion()).toHaveLength(1);
    expect(statusRegion()[0]).toHaveClass("sr-only");
    expect(statusRegion()[0]).toHaveTextContent("");

    await submitFor("Bybit");

    await waitFor(() => expect(statusRegion()[0]).toHaveTextContent(SAVED_NOTICE));
    expect(statusRegion()).toHaveLength(1);
    expect(statusRegion()[0]?.textContent).toBe(SAVED_NOTICE);
    // The visible notice is not a second live region, so nothing is read twice.
    expect(noteIn(bybitCard(), PENDING_NOTICE)?.closest("[role='status'], [aria-live], [role='alert']")).toBeNull();
  });

  it("says the card's read-only sentence after it to a screen reader, for a key that cannot trade", async () => {
    savePage({
      credentials: [storedKey("bybit", { last4: OLD_LAST4 })],
      reread: "pending",
      respond: () => Promise.resolve(jsonResponse(savedAnswer("bybit", { warnings: ["READ_ONLY_KEY"] }))),
    });
    await cardsDrawn();

    await submitFor("Bybit");

    await waitFor(() => expect(statusRegion()[0]?.textContent).toBe(`${SAVED_NOTICE} ${READ_ONLY_BYBIT}`));
  });

  it("test_the_notice_has_no_timer: it is still there after ten minutes and ends when the owner opens a form", async () => {
    savePage({
      credentials: [storedKey("bybit", { last4: OLD_LAST4 })],
      after: [storedKey("bybit", { last4: NEW_LAST4 })],
      pools: [pool("bybit"), pool("binance")],
    });
    // The timers are faked BEFORE the save, so a timer started by the save would be one of them. Time still
    // moves by itself (shouldAdvanceTime), so the page's reads and waitFor go on working.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      await cardsDrawn();
      await submitFor("Bybit");
      await waitFor(() => expect(noteIn(bybitCard(), SAVED_NOTICE)).toBeInTheDocument());

      await act(async () => {
        await vi.advanceTimersByTimeAsync(10 * 60 * 1000);
      });
      expect(noteIn(bybitCard(), SAVED_NOTICE)).toBeInTheDocument();

      fireEvent.click(toggleOf("Binance"));

      expect(noteIn(bybitCard(), SAVED_NOTICE)).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the card drawn from the answer while the list is behind, also after the owner opens a form", async () => {
    savePage({
      credentials: [storedKey("bybit", { last4: OLD_LAST4 })],
      reread: "pending",
      pools: [pool("bybit"), pool("binance")],
    });
    await cardsDrawn();
    await submitFor("Bybit");
    await waitFor(() => expect(noteIn(bybitCard(), PENDING_NOTICE)).toBeInTheDocument());

    // Another card's form: the old key of this card must not come back as if nothing had happened.
    fireEvent.click(toggleOf("Binance"));
    expect(bybitCard().textContent).not.toContain(OLD_LAST4);
    expect(within(bybitCard()).queryByText(`key ending in ${NEW_LAST4}`)).toBeInTheDocument();
    expect(noteIn(bybitCard(), PENDING_NOTICE)).toBeInTheDocument();

    // This card's own form: the key is stored (it was just saved), so the form says it replaces it.
    fireEvent.click(toggleOf("Bybit"));
    expect(formsOpen().map((heading) => heading.textContent)).toEqual(["Replace the Bybit key"]);
    expect(toggleOf("Bybit")).toHaveTextContent("Replace key");
    expect(bybitCard().textContent).not.toContain(OLD_LAST4);
  });

  it("ends the notice when the owner saves again, to the new key", async () => {
    savePage({
      credentials: [storedKey("bybit", { last4: OLD_LAST4 }), storedKey("binance", { last4: "ZZZZ" })],
      pools: [pool("bybit"), pool("binance")],
    });
    await cardsDrawn();
    await submitFor("Bybit");
    await waitFor(() => expect(noteIn(bybitCard(), SAVED_NOTICE)).toBeInTheDocument());

    await submitFor("Binance");

    await waitFor(() => expect(noteIn(bybitCard(), SAVED_NOTICE)).not.toBeInTheDocument());
    const binance = screen.getByRole("article", { name: "Binance" });
    await waitFor(() => expect(noteIn(binance, SAVED_NOTICE)).toBeInTheDocument());
  });

  it("does not close the form and does not change the card for a refusal", async () => {
    savePage({
      credentials: [storedKey("bybit", { last4: OLD_LAST4 })],
      respond: () => Promise.resolve(jsonResponse({ outcome: "KEY_REJECTED", detail: "x" }, 422)),
    });
    await cardsDrawn();
    fireEvent.click(toggleOf("Bybit"));
    const cardBefore = bybitCard().innerHTML.replace(/<section[\s\S]*<\/section>/, "");
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: KEY_VALUE } });
    fireEvent.change(screen.getByLabelText("API secret"), { target: { value: SECRET_VALUE } });

    fireEvent.click(screen.getByRole("button", { name: "Check and save" }));

    await waitFor(() => expect(screen.queryByRole("alert")).toBeInTheDocument());
    expect(formsOpen()).toHaveLength(1);
    expect(within(bybitCard()).queryByText(SAVED_NOTICE_PATTERN)).not.toBeInTheDocument();
    expect(statusRegion()[0]).toHaveTextContent("");
    expect(bybitCard().innerHTML.replace(/<section[\s\S]*<\/section>/, "")).toBe(cardBefore);
  });

  it("keeps the form open for an answer that could not be read, with the card above showing what the re-read found", async () => {
    savePage({
      credentials: [storedKey("bybit", { last4: OLD_LAST4 })],
      after: [storedKey("bybit", { last4: "9999" })],
      respond: () => Promise.resolve(jsonResponse({ detail: "boom" }, 500)),
    });
    await cardsDrawn();

    await submitFor("Bybit");

    await waitFor(() => expect(screen.queryByRole("alert")).toBeInTheDocument());
    expect(formsOpen()).toHaveLength(1);
    await waitFor(() => expect(within(bybitCard()).queryByText("key ending in 9999")).toBeInTheDocument());
    expect(within(bybitCard()).queryByText(SAVED_NOTICE_PATTERN)).not.toBeInTheDocument();
  });
});

describe("the page in Spanish", () => {
  it("writes its own texts in Spanish and none of design § J's English", async () => {
    await i18n.changeLanguage("es");
    stub({ kind: "pending" });
    mountPage();

    expect(screen.queryByRole("heading", { level: 2, name: "Claves de los exchanges" })).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Una clave por exchange. Las claves se cifran en el servidor y no se vuelven a mostrar; solo se ven los últimos cuatro caracteres.",
      ),
    ).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Cargando claves de los exchanges…")).toBeInTheDocument());
    expect(screen.getByText("Cargando claves de los exchanges…")).toHaveAttribute("role", "status");
    expect(document.body.textContent).not.toContain("Loading exchange keys");
    expect(document.body.textContent).not.toContain(INTRO);
  });

  it("writes the toggles, an open form, the notice and the status region in Spanish, and none of the English texts of Settings", async () => {
    await i18n.changeLanguage("es");
    savePage({
      credentials: [storedKey("bybit", { last4: OLD_LAST4 })],
      reread: "pending",
      respond: () => Promise.resolve(jsonResponse(savedAnswer("bybit", { warnings: ["READ_ONLY_KEY"] }))),
      pools: [pool("bybit"), pool("binance")],
    });
    await waitFor(() => expect(screen.queryAllByRole("article").length).toBeGreaterThan(0));
    expect(screen.queryByRole("button", { name: "Reemplazar clave Bybit" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Agregar clave Binance" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Agregar clave Binance" }));
    expect(screen.queryByRole("heading", { level: 4, name: "Agregar una clave de Binance" })).toBeInTheDocument();
    expect(document.body.textContent).toContain("Confirmé en Binance que esta clave tiene los retiros desactivados");
    expectNoEnglishSettingsText();

    fireEvent.click(screen.getByRole("button", { name: "Reemplazar clave Bybit" }));
    fireEvent.change(screen.getByLabelText("Clave de API"), { target: { value: KEY_VALUE } });
    fireEvent.change(screen.getByLabelText("Secreto de API"), { target: { value: SECRET_VALUE } });
    fireEvent.click(screen.getByRole("button", { name: "Comprobar y guardar" }));

    // The fixed Spanish of the notice (design § J's second table), exact.
    const pending = "Clave terminada en 7Q2d guardada. El resto de esta tarjeta aparece cuando la lista se haya leído de nuevo.";
    await waitFor(() => expect(within(bybitCard()).queryByText(pending)).toBeInTheDocument());
    expect(statusRegion()[0]?.textContent).toContain("Clave terminada en 7Q2d guardada.");
    expect(statusRegion()[0]?.textContent).toContain("Esta clave no puede operar.");
    expectNoEnglishSettingsText();
  });

  it("writes the first-line notice and the unnamed notice in Spanish, exactly", async () => {
    await i18n.changeLanguage("es");
    savePage({
      credentials: [storedKey("bybit", { last4: OLD_LAST4 })],
      after: [storedKey("bybit", { last4: NEW_LAST4 })],
    });
    await waitFor(() => expect(screen.queryAllByRole("article").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: "Reemplazar clave Bybit" }));
    fireEvent.change(screen.getByLabelText("Clave de API"), { target: { value: KEY_VALUE } });
    fireEvent.change(screen.getByLabelText("Secreto de API"), { target: { value: SECRET_VALUE } });
    fireEvent.click(screen.getByRole("button", { name: "Comprobar y guardar" }));

    await waitFor(() => expect(within(bybitCard()).queryByText("Clave terminada en 7Q2d guardada.")).toBeInTheDocument());
    expect(en.settings.card.savedNoHint).not.toBe(es.settings.card.savedNoHint);
    expect(es.settings.card.savedNoHint).toBe("Clave guardada.");
    expectNoEnglishSettingsText();
  });

  it("writes the failure, the stale line and the pools line in Spanish", async () => {
    await i18n.changeLanguage("es");
    stubApi(HEALTH, [], { kind: "status", status: 500, body: {} }, {}, undefined, {}, { kind: "status", status: 500, body: {} });
    mountPage();

    await waitFor(() => expect(screen.queryByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("No se pudieron cargar las claves de los exchanges.");
    expect(screen.queryByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});

// ---- `New key` and its select (owner decision 80, tasks p24.2 to p24.6) ----

const newKeyButton = () => screen.queryByRole("button", { name: "New key" });
const exchangeSelect = () => screen.queryByRole("combobox", { name: "Exchange" });

/** The select's options as they read, the placeholder first. */
function optionsOf(select: HTMLElement): string[] {
  return within(select).getAllByRole("option").map((option) => option.textContent ?? "");
}

/** Waits for `New key`, then presses it. */
async function pressNewKey() {
  await waitFor(() => expect(newKeyButton()).toBeInTheDocument());
  fireEvent.click(newKeyButton() as HTMLElement);
}

function choose(id: string) {
  fireEvent.change(exchangeSelect() as HTMLElement, { target: { value: id } });
}

describe("the `New key` button (p24.2)", () => {
  it("is drawn under the cards while a served exchange has no card", async () => {
    stub(ok(storedKey("bybit")));
    mountPage();
    await cardsDrawn();

    const button = await waitFor(() => found(newKeyButton(), "New key"));
    const list = screen.getByRole("list", { name: "Exchange keys" });
    expect(list.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("is drawn on a page with no card at all", async () => {
    stub(ok(), [disabled("bybit")]);
    mountPage();

    await waitFor(() => expect(newKeyButton()).toBeInTheDocument());
    expect(screen.queryAllByRole("article")).toEqual([]);
  });

  it("is not drawn when every served exchange has a key", async () => {
    stub(ok(storedKey("bybit"), storedKey("binance")));
    mountPage();
    await cardsDrawn();

    expect(cardNames()).toEqual(["Bybit", "Binance"]);
    expect(newKeyButton()).not.toBeInTheDocument();
  });

  it("is not drawn when the only served exchange left is degraded: its own card has `Add key`", async () => {
    stub(ok(storedKey("bybit")), [pool("bybit"), pool("binance")]);
    mountPage();
    await cardsDrawn();

    expect(screen.queryByRole("button", { name: "Add key Binance" })).toBeInTheDocument();
    expect(newKeyButton()).not.toBeInTheDocument();
  });

  it("is disabled while a save is in flight", async () => {
    const pending = new Promise<Response>(() => undefined);
    const extra: ExtraRoute = (url, init) =>
      url.endsWith("/credentials/bybit") && init?.method === "PUT" ? pending : undefined;
    stub(ok(storedKey("bybit")), [pool("bybit")], extra);
    mountPage();
    await cardsDrawn();
    await waitFor(() => expect(newKeyButton()).toBeInTheDocument());
    fireEvent.click(toggleOf("Bybit"));
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: KEY_VALUE } });
    fireEvent.change(screen.getByLabelText("API secret"), { target: { value: SECRET_VALUE } });

    fireEvent.click(screen.getByRole("button", { name: "Check and save" }));

    await waitFor(() => expect(newKeyButton()).toBeDisabled());
  });
});

describe("the select of `New key` (p24.3)", () => {
  it("replaces the button with a select labelled `Exchange`, focused, offering the served exchanges with no card", async () => {
    stub(ok(), [disabled("bybit"), { ...pool("pionex", "spot"), enabled: false }]);
    mountPage();

    await pressNewKey();

    const select = found(exchangeSelect(), "the select");
    expect(select).toHaveFocus();
    expect(newKeyButton()).not.toBeInTheDocument();
    // The file's order, by display name; Pionex has a pool, but the panel does not serve its key (decision 80 Q1).
    expect(optionsOf(select)).toEqual(["Choose an exchange", "Bybit", "Binance"]);
    expect((select as HTMLSelectElement).value).toBe("");
  });

  it("does not offer an exchange that already has a card", async () => {
    stub(ok(storedKey("bybit")));
    mountPage();
    await cardsDrawn();

    await pressNewKey();

    expect(optionsOf(found(exchangeSelect(), "the select"))).toEqual(["Choose an exchange", "Binance"]);
  });

  it("closes on Cancel and gives the focus back to `New key`", async () => {
    stub(ok(storedKey("bybit")));
    mountPage();
    await cardsDrawn();
    await pressNewKey();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(exchangeSelect()).not.toBeInTheDocument();
    await waitFor(() => expect(newKeyButton()).toHaveFocus());
  });
});

describe("the card chosen in the select (p24.4)", () => {
  it("draws the chosen exchange's card under the select, its key form open with its confirmations", async () => {
    stub(ok(storedKey("bybit")));
    mountPage();
    await cardsDrawn();
    await pressNewKey();

    choose("binance");

    const binance = screen.getByRole("article", { name: "Binance" });
    const select = found(exchangeSelect(), "the select");
    expect(select.compareDocumentPosition(binance) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(binance).queryByRole("heading", { level: 4, name: "Add a Binance key" })).toBeInTheDocument();
    expect(within(binance).queryByLabelText(WITHDRAWALS_LABEL)).toBeInTheDocument();
    expect(within(binance).getByLabelText("API key")).toHaveFocus();
    // It is not one of the list's cards: the list holds the cards of keys that exist.
    expect(binance.closest("ul")).toBeNull();
  });

  it("swaps the card when another exchange is chosen", async () => {
    stub(ok(), [disabled("bybit")]);
    mountPage();
    await pressNewKey();

    choose("bybit");
    expect(cardNames()).toEqual(["Bybit"]);
    choose("binance");

    expect(cardNames()).toEqual(["Binance"]);
    expect(formsOpen().map((heading) => heading.textContent)).toEqual(["Add a Binance key"]);
  });

  it("closes the select and the card when the form is closed, and gives the focus back to `New key`", async () => {
    stub(ok(storedKey("bybit")));
    mountPage();
    await cardsDrawn();
    await pressNewKey();
    choose("binance");

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(exchangeSelect()).not.toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Binance" })).not.toBeInTheDocument();
    await waitFor(() => expect(newKeyButton()).toHaveFocus());
  });

  it("closes the select and the card when another card's form is opened", async () => {
    stub(ok(storedKey("bybit")));
    mountPage();
    await cardsDrawn();
    await pressNewKey();
    choose("binance");

    fireEvent.click(toggleOf("Bybit"));

    expect(exchangeSelect()).not.toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Binance" })).not.toBeInTheDocument();
    expect(formsOpen().map((heading) => heading.textContent)).toEqual(["Replace the Bybit key"]);
  });
});

describe("a key saved from the select's card (p24.5)", () => {
  it("closes the select, puts the card in the list from the answer, focuses its `Replace key` and says it", async () => {
    // No key and no pool yet, so Bybit is still left to offer once Binance has its key.
    savePage({
      credentials: [],
      after: [storedKey("binance", { last4: NEW_LAST4 })],
      reread: "pending",
      pools: [],
    });
    await pressNewKey();
    choose("binance");

    fireEvent.change(screen.getByLabelText("API key"), { target: { value: KEY_VALUE } });
    fireEvent.change(screen.getByLabelText("API secret"), { target: { value: SECRET_VALUE } });
    fireEvent.click(screen.getByLabelText(WITHDRAWALS_LABEL));
    fireEvent.click(screen.getByLabelText(FUTURES_LABEL));
    fireEvent.click(screen.getByRole("button", { name: "Check and save" }));

    await waitFor(() => expect(exchangeSelect()).not.toBeInTheDocument());
    const list = screen.getByRole("list", { name: "Exchange keys" });
    const binance = screen.getByRole("article", { name: "Binance" });
    expect(binance.closest("ul")).toBe(list);
    expect(screen.getAllByRole("article", { name: "Binance" })).toHaveLength(1);
    expect(noteIn(binance, PENDING_NOTICE)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Replace key Binance" })).toHaveFocus());
    expect(statusRegion().map((region) => region.textContent)).toContain(SAVED_NOTICE);
    // Bybit is still left: `New key` is back, closed.
    expect(newKeyButton()).toBeInTheDocument();
  });

  it("keeps the select and the card when the save is refused", async () => {
    savePage({
      credentials: [storedKey("bybit")],
      respond: () => Promise.resolve(jsonResponse({ detail: { code: "KEY_REJECTED" } }, 422)),
    });
    await cardsDrawn();
    await pressNewKey();
    choose("binance");

    fireEvent.change(screen.getByLabelText("API key"), { target: { value: KEY_VALUE } });
    fireEvent.change(screen.getByLabelText("API secret"), { target: { value: SECRET_VALUE } });
    fireEvent.click(screen.getByLabelText(WITHDRAWALS_LABEL));
    fireEvent.click(screen.getByLabelText(FUTURES_LABEL));
    fireEvent.click(screen.getByRole("button", { name: "Check and save" }));

    await waitFor(() => expect(screen.queryByRole("button", { name: "Checking…" })).not.toBeInTheDocument());
    expect(exchangeSelect()).toBeInTheDocument();
    expect(formsOpen().map((heading) => heading.textContent)).toEqual(["Add a Binance key"]);
  });
});

describe("`New key` in Spanish (p24.6)", () => {
  it("writes the button, the select, its placeholder and Cancel in Spanish", async () => {
    await i18n.changeLanguage("es");
    stub(ok(storedKey("bybit")));
    mountPage();
    await cardsDrawn();

    const button = await waitFor(() => found(screen.queryByRole("button", { name: "Nueva clave" }), "Nueva clave"));
    // Checked before the select opens: "Cancelar" holds the English "Cancel", which the check looks for.
    expectNoEnglishSettingsText();
    fireEvent.click(button);

    const select = found(screen.queryByRole("combobox", { name: "Exchange" }), "the select");
    expect(optionsOf(select)).toEqual(["Elija un exchange", "Binance"]);
    expect(screen.queryByRole("button", { name: "Cancelar" })).toBeInTheDocument();
    expect(es.settings.keys).toMatchObject({
      newKey: "Nueva clave",
      exchange: "Exchange",
      choose: "Elija un exchange",
      cancel: "Cancelar",
    });
    expect(screen.queryByText("Choose an exchange")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });
});
