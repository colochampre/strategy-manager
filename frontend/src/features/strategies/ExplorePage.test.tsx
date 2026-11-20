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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Explore", () => {
  it("shows a strategy with its author, market and figures, for a user with no pool at all", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ id: ID })])));
    open();

    const row = await screen.findByTestId("public-strategy-row");
    expect(within(row).getByRole("link", { name: "Alpha" })).toHaveAttribute("href", `/strategies/explore/${ID}`);
    expect(within(row).getByText(i18n.t("strategies.public.by", { name: "Ana" }), { exact: false })).toBeInTheDocument();
    expect(within(row).getByTestId("public-market")).toHaveTextContent("bybit · usdt-m · USDT");
    // The public record serves a win rate of 0.6 over 3 closed trades: the card writes the count it stands for.
    expect(within(row).getByTestId("public-wins")).toHaveTextContent(/^2\/3$/);
    expect(within(row).getByTestId("public-return")).toHaveTextContent("+12.5%");
    expect(within(row).getByTestId("public-subscribers")).toHaveTextContent(/^2$/);
    expect(within(row).getByTestId("public-capital")).toHaveTextContent("1,500.00USDT");
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
    expect(row.textContent).not.toContain("AAVEUSDT");
    expect(api.mock.calls.filter(([url]) => String(url).endsWith("/positions/open"))).toHaveLength(0);
  });

  it("adds the deepest fall and the win rate to the figures, and no days active (owner, 2026-11-17)", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ max_drawdown: "-0.05", win_rate: "0.6" })])));
    open();

    const row = await screen.findByTestId("public-strategy-row");
    expect(within(row).getByTestId("public-deepest")).toHaveTextContent(/^[-−]5\.0\s?%$/);
    expect(within(row).getByTestId("public-winrate")).toHaveTextContent(/^60\s?%$/);
    expect(within(row).queryByTestId("public-uptime")).not.toBeInTheDocument();
  });

  it("shows a strategy of another author as enabled or disabled, in words", async () => {
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
    expect(within(alpha as HTMLElement).getByTestId("public-enabled")).toHaveAccessibleName(i18n.t("strategies.detail.enabled"));
    expect(within(beta as HTMLElement).getByTestId("public-enabled")).toHaveAccessibleName(i18n.t("strategies.detail.disabled"));
  });

  it("opens the strategy from anywhere on the card, through the one link", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ id: ID })])));
    open();

    const row = await screen.findByTestId("public-strategy-row");
    expect(row).toHaveClass("relative");
    expect(within(row).getAllByRole("link")).toHaveLength(1);
    expect(within(row).getByRole("link", { name: "Alpha" })).toHaveClass("after:absolute", "after:inset-0");
  });

  it("shows no open position of anyone, and does not even ask for them", async () => {
    const api = serve(() => Promise.resolve(jsonResponse([publicStrategy({ id: ID })])));
    open();

    const row = await screen.findByTestId("public-strategy-row");
    expect(within(row).queryByRole("list")).not.toBeInTheDocument();
    expect(api.mock.calls.some(([url]) => String(url).endsWith("/positions/open"))).toBe(false);
  });

  it("groups the record under Total PnL, Max drawdown and Win rate, the capital under AuM (owner, 2026-11-17)", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy()])));
    open();

    const row = await screen.findByTestId("public-strategy-row");
    for (const [group, key, label] of [
      ["pnl", "return", "Total PnL"],
      ["drawdown", "deepest", "Max drawdown"],
      ["profitable", "winrate", "Win rate"],
      ["aum", "capital", "AuM"],
    ] as const) {
      const found = within(row).getByTestId(`public-group-${group}`);
      expect(found.querySelector("dt"), group).toHaveTextContent(label);
      expect(within(found).getByTestId(`public-${key}`), group).toBeInTheDocument();
    }
  });

  it("draws the dates under a calendar and the subscribers as people (owner, 2026-11-06)", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy()])));
    open();

    const row = await screen.findByTestId("public-strategy-row");
    expect(within(row).getByRole("img", { name: "Age" })).toHaveClass("lucide-calendar");
    expect(within(row).getByRole("img", { name: "Live subscribers" })).toHaveClass("lucide-users");
  });

  it("explains an icon on hover", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy()])));
    open();

    const row = await screen.findByTestId("public-strategy-row");
    fireEvent.mouseEnter(within(row).getByRole("img", { name: "Live subscribers" }).parentElement as HTMLElement);
    expect(within(row).getByRole("tooltip")).toHaveTextContent("Live subscribers");
  });

  it("colours a loss as a loss", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ unleveraged_return_before_fees: "-0.04" })])));
    open();

    expect(await screen.findByTestId("public-return")).toHaveClass("text-loss");
  });

  it("dates the strategy on its market line, from its creation to today (owner, 2026-11-17)", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-06T12:00:00Z"));
    try {
      serve(() => Promise.resolve(jsonResponse([publicStrategy({ created_at: "2025-07-01T10:00:00Z" })])));
      open();

      const age = await screen.findByTestId("public-age");
      expect(age).toHaveTextContent(/^Jul 1, 2025 – Nov 6, 2026$/);
      expect(screen.getByTestId("public-market")).toContainElement(age);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows the capital's dash where there is no return yet (owner, 2026-11-08)", async () => {
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

    expect(await screen.findByTestId("public-capital")).toHaveTextContent("0.00USDT");
  });

  it("says so when nothing is public", async () => {
    serve(() => Promise.resolve(jsonResponse([])));
    open();

    expect(await screen.findByText(i18n.t("strategies.explore.empty"))).toBeInTheDocument();
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
    expect(button).toHaveClass("inline-flex", "min-h-11", "items-center", "gap-1.5", "bg-gain");
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
