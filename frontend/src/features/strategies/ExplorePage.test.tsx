import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import {
  jsonResponse,
  openPosition,
  openState,
  publicStrategy,
  renderAt,
  resetExchangeScope,
  setViewport,
  SIGNED_UP,
  stubApi,
  unlock,
} from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";

function serve(answer: () => Promise<Response>, me: Record<string, unknown> = {}) {
  return stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) => {
    if (url.endsWith("/api/public/strategies")) return answer();
    if (url.endsWith("/api/me")) {
      return Promise.resolve(
        jsonResponse({ email: "a@example.com", is_admin: true, mode: "LIVE", dry_run_brake: false, ...SIGNED_UP, ...me }),
      );
    }
    return undefined;
  });
}

function open() {
  renderAt(<AppRoutes />, "/strategies/explore");
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
  setViewport("wide");
});

afterEach(async () => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  await i18n.changeLanguage("en");
});

/** The table of S15 (ex15), named by its card's title. */
const exploreTable = () => screen.findByRole("table", { name: i18n.t("strategies.table.title.explore") });

describe("Explore as a table (S15)", () => {
  it("is one table in a card with its title and count, the columns of the prototype, for a user with no pool at all", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ id: ID })])));
    open();

    const table = await exploreTable();
    expect(screen.getByTestId("public-strategies-count")).toHaveTextContent("1 strategy");
    expect(within(table).getAllByRole("columnheader").map((head) => head.textContent)).toEqual([
      "Strategy",
      "Author",
      "Exchange",
      "Since",
      "PnL (%)",
      "Max drawdown",
      "Win rate",
      "Subs.",
      "AuM (USDT)",
    ]);
    expect(screen.getByTestId("public-strategy-row").tagName).toBe("TR");
  });

  it("starts the record columns at the start and ends Subs. and AuM at the end (L23)", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ id: ID })])));
    open();

    const table = await exploreTable();
    const heads = within(table).getAllByRole("columnheader");
    const cells = within(screen.getByTestId("public-strategy-row")).getAllByRole("cell");
    for (const index of [4, 5, 6]) {
      expect(heads[index], `head ${index}`).toHaveClass("text-left");
      expect(cells[index], `cell ${index}`).toHaveClass("text-left");
    }
    for (const index of [7, 8]) {
      expect(heads[index], `head ${index}`).toHaveClass("text-right");
      expect(cells[index], `cell ${index}`).toHaveClass("text-right");
    }
  });

  it("shows a strategy with its author, exchange and figures, the name a link to its public page", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ id: ID })])));
    open();

    const row = await screen.findByTestId("public-strategy-row");
    expect(within(row).getAllByRole("link")).toHaveLength(1);
    expect(within(row).getByRole("link", { name: "Alpha" })).toHaveAttribute("href", `/strategies/explore/${ID}`);
    expect(within(row).getByTestId("public-origin").textContent).toBe("Ana");
    const exchange = within(row).getByTestId("public-exchange");
    expect(exchange.textContent).toBe("Bybit");
    fireEvent.mouseEnter(exchange.parentElement as HTMLElement);
    expect(within(row).getByRole("tooltip")).toHaveTextContent("Bybit · USDT-M · USDT");
    // The public record serves a win rate of 0.6 over 3 closed trades: the cell writes the count it stands for.
    expect(within(row).getByTestId("public-wins")).toHaveTextContent(/^2\/3$/);
    expect(within(row).getByTestId("public-winrate").closest("td")).toHaveTextContent(/^60% · 2\/3$/);
    expect(within(row).getByTestId("public-return")).toHaveTextContent(/^\+12\.5%$/);
    expect(within(row).getByTestId("public-subscribers")).toHaveTextContent(/^2$/);
    expect(within(row).getByTestId("public-capital").textContent).toBe("1,500.00");
  });

  it("speaks Spanish as the prototype does: the columns, the dates and the percent sign right after the number (ex15)", async () => {
    await i18n.changeLanguage("es");
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ id: ID, created_at: "2026-06-11T10:00:00Z" })])));
    open();

    const table = await screen.findByRole("table", { name: "Estrategias públicas" });
    expect(within(table).getAllByRole("columnheader").map((head) => head.textContent)).toEqual([
      "Estrategia",
      "Autor",
      "Exchange",
      "Desde",
      "PnL (%)",
      "Caída máx.",
      "Acierto",
      "Subs.",
      "AuM (USDT)",
    ]);
    expect(screen.getByTestId("public-return").textContent).toBe("+12,5%");
    expect(screen.getByTestId("public-age").textContent).toMatch(/^11 jun\.? 2026$/);
    expect(screen.getByTestId("public-strategies-count")).toHaveTextContent("1 estrategia");
  });

  it("draws no PnL in money: the public record carries none, another author's PnL is theirs alone", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ id: ID })])));
    open();

    const row = await screen.findByTestId("public-strategy-row");
    expect(within(row).queryByTestId("public-pnl")).not.toBeInTheDocument();
    expect(within(row).queryByTestId("public-uptime")).not.toBeInTheDocument();
    expect(within(row).queryByTestId("public-group-setup")).not.toBeInTheDocument();
  });

  it("shows no open position of anyone, even the reader's own holding in that strategy (owner, 2026-11-08)", async () => {
    const api = stubApi(
      { kind: "ok", body: {} },
      [],
      { kind: "ok", body: [] },
      {},
      (url) => (url.endsWith("/api/public/strategies") ? Promise.resolve(jsonResponse([publicStrategy({ id: ID })])) : undefined),
      {},
      undefined,
      { kind: "ok", body: openState([openPosition({ strategy_id: ID, markets: ["AAVEUSDT"] })]) },
    );
    open();

    const row = await screen.findByTestId("public-strategy-row");
    expect(within(row).queryAllByRole("listitem")).toHaveLength(0);
    expect(within(row).queryByRole("list")).not.toBeInTheDocument();
    expect(row.textContent).not.toContain("AAVEUSDT");
    expect(api.mock.calls.filter(([url]) => String(url).endsWith("/positions/open"))).toHaveLength(0);
  });

  it("adds the deepest fall and the win rate to the figures, and no days active (owner, 2026-11-17)", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ max_drawdown: "-0.05", win_rate: "0.6" })])));
    open();

    const row = await screen.findByTestId("public-strategy-row");
    expect(within(row).getByTestId("public-deepest")).toHaveTextContent(/^[-−]5\.0%$/);
    expect(within(row).getByTestId("public-winrate")).toHaveTextContent(/^60%$/);
    expect(within(row).queryByTestId("public-uptime")).not.toBeInTheDocument();
  });

  it("marks a strategy of another author with a gain dot when it runs and a grey one when it does not, the word in a tooltip", async () => {
    serve(() =>
      Promise.resolve(
        jsonResponse([
          publicStrategy({ id: ID, enabled: true }),
          publicStrategy({ id: "22222222-2222-4222-8222-222222222222", name: "Beta", enabled: false }),
        ]),
      ),
    );
    open();

    const [alpha, beta] = await screen.findAllByTestId("public-strategy-row");
    const on = within(alpha as HTMLElement).getByTestId("public-enabled");
    expect(on).toHaveAccessibleName(i18n.t("strategies.detail.enabled"));
    expect(on).toHaveClass("bg-gain");
    const off = within(beta as HTMLElement).getByTestId("public-enabled");
    expect(off).toHaveAccessibleName(i18n.t("strategies.detail.disabled"));
    expect(off).toHaveClass("bg-ink-3");
    fireEvent.mouseEnter(off.parentElement as HTMLElement);
    expect(within(beta as HTMLElement).getByRole("tooltip")).toHaveTextContent(i18n.t("strategies.detail.disabled"));
  });

  it("colours a loss as a loss", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ unleveraged_return_before_fees: "-0.04" })])));
    open();

    expect(await screen.findByTestId("public-return")).toHaveClass("text-loss");
  });

  it("shows the day the strategy started, from its creation, the whole period to today in the tooltip (owner, 2026-11-17)", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-06T12:00:00Z"));
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ created_at: "2025-07-01T10:00:00Z" })])));
    open();

    const since = await screen.findByTestId("public-age");
    expect(since).toHaveTextContent(/^Jul 01, 2025$/);
    fireEvent.mouseEnter(since.parentElement as HTMLElement);
    expect(within(screen.getByTestId("public-strategy-row")).getByRole("tooltip")).toHaveTextContent("Jul 1, 2025 – Nov 6, 2026");
  });

  it("shows the dash where there is no return yet (owner, 2026-11-08)", async () => {
    serve(() =>
      Promise.resolve(jsonResponse([publicStrategy({ closed_trade_count: 0, unleveraged_return_before_fees: "0" })])),
    );
    open();

    expect(await screen.findByTestId("public-return")).toHaveTextContent(/^—$/);
  });

  it("claims no return, deepest fall or win rate before a real trade has closed", async () => {
    serve(() =>
      Promise.resolve(
        jsonResponse([
          publicStrategy({ closed_trade_count: 0, unleveraged_return_before_fees: "0", max_drawdown: "0", win_rate: null }),
        ]),
      ),
    );
    open();

    expect(await screen.findByTestId("public-winrate")).toBeInTheDocument();
    expect(screen.queryByTestId("public-wins")).not.toBeInTheDocument();
    for (const key of ["return", "deepest", "winrate"]) {
      const figure = screen.getByTestId(`public-${key}`);
      expect(figure, key).toHaveTextContent(/^—$/);
      expect(figure, key).not.toHaveClass("text-gain");
      expect(figure, key).not.toHaveClass("text-loss");
    }
  });

  it("under the brake shows no capital, and leaves the why to the header's (i) (L.10)", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ live_subscribers: 0, capital: null })])), {
      dry_run_brake: true,
      ...SIGNED_UP,
    });
    open();

    expect(await screen.findByTestId("public-capital")).toHaveTextContent("—");
    expect(screen.queryByText(i18n.t("mode.brakeInfo"))).not.toBeInTheDocument();
  });

  it("writes a capital of zero as zero, not as an absence", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ live_subscribers: 0, capital: "0" })])));
    open();

    expect(await screen.findByTestId("public-capital")).toHaveTextContent(/^0\.00$/);
  });

  it("writes each capital with its own currency when the strategies' differ, and says none in the header (rule 7)", async () => {
    serve(() =>
      Promise.resolve(
        jsonResponse([
          publicStrategy({ id: ID, capital: "1500" }),
          publicStrategy({ id: "22222222-2222-4222-8222-222222222222", name: "Coin", settlement_currency: "BTC", capital: "0.5" }),
        ]),
      ),
    );
    open();

    const table = await exploreTable();
    expect(within(table).getAllByRole("columnheader").map((head) => head.textContent)).toContain("AuM");
    const capitals = screen.getAllByTestId("public-capital").map((cell) => cell.textContent);
    expect(capitals).toEqual(expect.arrayContaining(["1,500.00USDT", "0.50000000BTC"]));
  });

  it("says so when nothing is public", async () => {
    serve(() => Promise.resolve(jsonResponse([])));
    open();

    expect(await screen.findByText(i18n.t("strategies.explore.empty"))).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("reads a failed list as an error, never as an empty one", async () => {
    serve(() => Promise.resolve(jsonResponse({ detail: "down" }, 500)));
    open();

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.explore.error"));
    expect(screen.queryByText(i18n.t("strategies.explore.empty"))).not.toBeInTheDocument();
  });

  it("says it is loading while the list is on its way", async () => {
    serve(() => new Promise<Response>(() => undefined));
    open();

    expect(await screen.findByText(i18n.t("strategies.explore.loading"))).toBeInTheDocument();
  });

  it("keeps the search, I have a code and the sort together above the table, in one card", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ id: ID })])));
    open();
    await exploreTable();

    const card = screen.getByTestId("list-toolbar").closest("section") as HTMLElement;
    expect(within(card).getByRole("searchbox")).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: i18n.t("strategies.entry.haveCode") })).toBeInTheDocument();
    expect(within(card).getByRole("group", { name: i18n.t("strategies.sort.label") })).toBeInTheDocument();
    expect(within(card).queryByRole("table")).toBeNull();
  });
});

describe("Explore's sort", () => {
  const A = publicStrategy({
    id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    name: "Alpha",
    created_at: "2026-10-01T10:00:00Z",
    closed_trade_count: 3,
    unleveraged_return_before_fees: "0.125",
    subscribers: 3,
    live_subscribers: 2,
    capital: "1500",
  });
  const B = publicStrategy({
    id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    name: "Bravo",
    created_at: "2026-09-01T10:00:00Z",
    closed_trade_count: 10,
    unleveraged_return_before_fees: "0.30",
    subscribers: 1,
    live_subscribers: 0,
    capital: "200",
  });
  const C = publicStrategy({
    id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    name: "Charlie",
    created_at: "2026-10-20T10:00:00Z",
    closed_trade_count: 0,
    unleveraged_return_before_fees: "0",
    subscribers: 7,
    live_subscribers: 5,
    capital: null,
  });

  const names = () =>
    screen.getAllByTestId("public-strategy-row").map((row) => within(row).getAllByRole("link")[0]?.textContent);
  const press = (name: string) => fireEvent.click(screen.getByRole("button", { name }));

  async function start() {
    serve(() => Promise.resolve(jsonResponse([A, B, C])));
    open();
    await screen.findAllByTestId("public-strategy-row");
  }

  it("orders by return, largest first, until the reader chooses otherwise", async () => {
    await start();

    expect(names()).toEqual(["Bravo", "Alpha", "Charlie"]);
    expect(screen.getByRole("button", { name: "Return, descending" })).toHaveAttribute("aria-pressed", "true");
  });

  it("flips the return to ascending on a second click and keeps a strategy with no return last", async () => {
    await start();

    press("Return, descending");

    expect(names()).toEqual(["Alpha", "Bravo", "Charlie"]);
    expect(screen.getByRole("button", { name: "Return, ascending" })).toBeInTheDocument();
  });

  it("flips it back to descending on a third", async () => {
    await start();

    press("Return, descending");
    press("Return, ascending");

    expect(names()).toEqual(["Bravo", "Alpha", "Charlie"]);
  });

  it("orders by age, the oldest first", async () => {
    await start();

    press("Age");

    expect(names()).toEqual(["Bravo", "Alpha", "Charlie"]);
    press("Age, descending");
    expect(names()).toEqual(["Charlie", "Alpha", "Bravo"]);
  });

  it("orders by closed trades", async () => {
    await start();

    press("Closed trades");

    expect(names()).toEqual(["Bravo", "Alpha", "Charlie"]);
  });

  it("orders by subscribers", async () => {
    await start();

    press("Subscribers");

    expect(names()).toEqual(["Charlie", "Alpha", "Bravo"]);
  });

  it("orders by capital and keeps a strategy with none last both ways", async () => {
    await start();

    press("Capital");
    expect(names()).toEqual(["Alpha", "Bravo", "Charlie"]);
    press("Capital, descending");
    expect(names()).toEqual(["Bravo", "Alpha", "Charlie"]);
  });

  it("starts a newly chosen key descending even after the last one ended ascending", async () => {
    await start();

    press("Return, descending");
    press("Subscribers");

    expect(names()).toEqual(["Charlie", "Alpha", "Bravo"]);
    expect(screen.getByRole("button", { name: "Subscribers, descending" })).toBeInTheDocument();
  });
});

describe("I have a code, in the form of New strategy (owner, 2026-11-08)", () => {
  it("is a green button with a key, in the row where New strategy sits, and shows no form until pressed", async () => {
    serve(() => Promise.resolve(jsonResponse([])));
    open();

    const button = await screen.findByRole("button", { name: i18n.t("strategies.entry.haveCode") });
    // The prototype's outline (L26), as tall as the search beside it.
    expect(button).toHaveClass("inline-flex", "h-10", "items-center", "gap-1.5", "border-gain/45", "text-gain-bright");
    expect(button).not.toHaveClass("bg-gain");
    const icon = button.querySelector("svg");
    expect(icon).toHaveClass("lucide-key-round", "size-4", "shrink-0");
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(button.firstElementChild).toBe(icon);
    expect(button.parentElement).toHaveClass("flex", "flex-wrap", "justify-end");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("opens a dialog with the code, its hint and its Open button", async () => {
    serve(() => Promise.resolve(jsonResponse([])));
    open();

    fireEvent.click(await screen.findByRole("button", { name: i18n.t("strategies.entry.haveCode") }));

    const dialog = screen.getByRole("dialog", { name: i18n.t("strategies.entry.haveCode") });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(within(dialog).getByRole("textbox", { name: i18n.t("strategies.entry.codeLabel") })).toHaveFocus();
    expect(within(dialog).getByText(i18n.t("strategies.entry.codeHint"))).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: i18n.t("strategies.entry.open") })).toBeDisabled();
  });

  it("closes on Escape and leaves the page as it was", async () => {
    serve(() => Promise.resolve(jsonResponse([])));
    open();

    fireEvent.click(await screen.findByRole("button", { name: i18n.t("strategies.entry.haveCode") }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: i18n.t("strategies.entry.haveCode") })).toBeInTheDocument();
  });

  it("closes from its own Cancel button", async () => {
    serve(() => Promise.resolve(jsonResponse([])));
    open();

    fireEvent.click(await screen.findByRole("button", { name: i18n.t("strategies.entry.haveCode") }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: i18n.t("strategies.entry.cancel") }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
