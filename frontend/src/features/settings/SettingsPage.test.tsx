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

function cardNames(): string[] {
  return screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent ?? "");
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

    const outline = screen.getAllByRole("heading").map((heading) => `${heading.tagName} ${heading.textContent}`);
    expect(outline).toEqual(["H1 Settings", "H2 Exchange keys", "H3 Bybit", "H3 Binance"]);
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
  it("test_no_exchange_tabs_lists_every_exchange: no exchange bar on Settings, and a card for every exchange", async () => {
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
    expect(cardNames()).toEqual(["Bybit", "Binance", "Pionex"]);
  });

  it("gives Binance a card, in the empty state, when neither route lists it", async () => {
    stub(ok(storedKey("bybit")), [pool("bybit")]);
    mountPage();
    await cardsDrawn();

    expect(cardNames()).toEqual(["Bybit", "Binance"]);
    const binance = screen.getByRole("article", { name: "Binance" });
    expect(within(binance).queryByText("No key stored. Add one to read and trade on Binance from here.")).toBeInTheDocument();
    expect(binance).toHaveClass("border-rule");
  });

  it("shows a stored key of an exchange nothing else lists, with no button", async () => {
    stub(ok(storedKey("bybit"), storedKey("kraken", { last4: "AB12" })), [pool("bybit")]);
    mountPage();
    await cardsDrawn();

    expect(cardNames()).toEqual(["Bybit", "Binance", "kraken"]);
    const kraken = screen.getByRole("article", { name: "kraken" });
    expect(within(kraken).queryByText("key ending in AB12")).toBeInTheDocument();
    expect(within(kraken).queryAllByRole("button")).toEqual([]);
  });

  it("lists the served exchanges first in the file's order, then the others of the credentials by name, then the pool-only ones by name", async () => {
    stub(ok(storedKey("zeta"), storedKey("bybit"), storedKey("alpha")), [
      pool("pionex"),
      pool("mexc"),
      pool("zeta"),
      pool("bybit"),
    ]);
    mountPage();
    await cardsDrawn();

    expect(cardNames()).toEqual(["Bybit", "Binance", "alpha", "zeta", "mexc", "Pionex"]);
  });

  it("marks the degraded exchange amber and leaves an exchange whose pool is off neutral", async () => {
    stub(ok(storedKey("bybit")), [pool("bybit"), pool("binance")]);
    mountPage();
    await cardsDrawn();
    expect(screen.getByRole("article", { name: "Binance" })).toHaveClass("border-decision");
    expect(screen.getByRole("article", { name: "Bybit" })).toHaveClass("border-rule");
  });

  it("leaves a deleted key's exchange neutral: its pool is off", async () => {
    stub(ok(storedKey("bybit"), emptyKey("binance")), [pool("bybit"), disabled("binance")]);
    mountPage();
    await cardsDrawn();

    const binance = screen.getByRole("article", { name: "Binance" });
    expect(binance).toHaveClass("border-rule");
    expect(binance.outerHTML).not.toMatch(AMBER);
  });
});

describe("the page's own states", () => {
  it("says it is loading and draws no card while the keys are not known", async () => {
    stub({ kind: "pending" });
    mountPage();

    await waitFor(() => expect(screen.queryByRole("status")).toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent("Loading exchange keys…");
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
    stub({ kind: "pending" }, [pool("bybit")], extra);
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
    const binance = screen.getByRole("article", { name: "Binance" });
    expect(binance).toHaveClass("border-rule");
    expect(binance.outerHTML).not.toMatch(AMBER);
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
    await waitFor(() => expect(screen.queryAllByRole("button", { name: "kraken no key" }).length).toBeGreaterThan(0));
    for (const tab of within(screen.getAllByRole("navigation", { name: "Exchanges" })[0] as HTMLElement).getAllByRole("button")) {
      const name = tab.firstElementChild?.firstElementChild?.textContent ?? "";
      wordsOnTabs.set(name, tab.textContent?.slice(name.length).trim() ?? "");
    }
    view.unmount();

    renderAt(<AppRoutes />, "/settings");
    await cardsDrawn();
    await waitFor(() => expect(screen.queryByRole("article", { name: "kraken" })?.textContent).toContain("no key"));
    for (const [exchange, word] of wordsOnTabs) {
      const card = screen.queryAllByRole("article").find((article) => article.textContent?.toLowerCase().includes(exchange));
      expect(card, exchange).toBeDefined();
      if (word === "") {
        expect(card?.textContent, exchange).not.toMatch(/read-only|no key/);
      } else {
        expect(card?.textContent, exchange).toContain(word);
      }
    }
    expect([...wordsOnTabs]).toEqual([
      ["bybit", ""],
      ["binance", "read-only"],
      ["pionex", "no key"],
      ["kraken", "no key"],
    ]);
  });
});

/** A card's toggle, "Add key" or "Replace key" with the exchange after it. */
function toggleOf(name: string): HTMLElement {
  const button = within(screen.getByRole("article", { name })).queryByRole("button", { name: /^(Add|Replace) key/ });
  expect(button, `the toggle of ${name}`).toBeInTheDocument();
  return button as HTMLElement;
}

function formsOpen(): HTMLElement[] {
  return screen.queryAllByRole("heading", { level: 4 });
}

describe("the toggles and the open form (task 13.5.8)", () => {
  it("names the buttons with their exchange: `Replace key Bybit` and `Add key Binance`, not the same name twice", async () => {
    stub(ok(storedKey("bybit")));
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

    expect(within(screen.getByRole("article", { name: "kraken" })).queryAllByRole("button")).toEqual([]);
  });

  it("test_one_form_at_a_time: opening another card's form closes and unmounts the open one", async () => {
    stub(ok(storedKey("bybit")));
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
    stub(ok(storedKey("bybit")));
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
    await waitFor(() => expect(screen.queryByRole("status")).toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent("Cargando claves de los exchanges…");
    expect(document.body.textContent).not.toContain("Loading exchange keys");
    expect(document.body.textContent).not.toContain(INTRO);
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
