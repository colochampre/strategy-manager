import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Figure } from "@/features/strategies/PublicFigures";
import { StrategyCard } from "@/features/strategies/StrategyCard";
import type { CardFigures, StrategyCardProps } from "@/features/strategies/StrategyCard";
import i18n from "@/shared/i18n";
import { renderAt } from "@/test/harness";

const DAY_S = 86_400;

const FIGURES: CardFigures = {
  trades: 3,
  ret: 0.125,
  deepest: -0.05,
  winRate: 0.6,
  subscribers: 2,
  capital: { amount: 1500, currency: "USDT" },
};

function draw(props: Partial<StrategyCardProps> = {}) {
  renderAt(
    <ul>
      <StrategyCard
        prefix="card"
        rowTestId="card-row"
        to="/strategies/explore/s-1"
        name="Alpha"
        byline="by Ana"
        enabled={true}
        market="bybit · usdt-m · USDT"
        since="2026-10-01T10:00:00Z"
        sinceKind="age"
        uptime={{ seconds: 12 * DAY_S + 3600, first_enabled_at: "2026-09-18T10:00:00Z", baseline: false }}
        figures={FIGURES}
        {...props}
      />
    </ul>,
  );
  return screen.getByTestId("card-row");
}

const FIGURE_ORDER = ["age", "uptime", "trades", "return", "deepest", "winrate", "subscribers", "capital"];

afterEach(() => {
  vi.useRealTimers();
});

describe("what a card names", () => {
  it("names the strategy as a link, its author and its market", () => {
    const row = draw();

    expect(within(row).getByRole("link", { name: "Alpha" })).toHaveAttribute("href", "/strategies/explore/s-1");
    expect(within(row).getByText("by Ana")).toBeInTheDocument();
    expect(within(row).getByTestId("card-market")).toHaveTextContent(/^bybit · usdt-m · USDT$/);
  });

  it("draws no author line when there is none to name", () => {
    const row = draw({ byline: null });

    expect(within(row).queryByTestId("card-origin")).not.toBeInTheDocument();
  });

  it("marks a running strategy with a filled dot in the gain colour, its word the dot's name and tooltip (L.12)", () => {
    draw({ enabled: true });

    const dot = screen.getByTestId("card-enabled");
    expect(dot).toHaveAccessibleName(i18n.t("strategies.detail.enabled"));
    expect(dot).toHaveAttribute("role", "img");
    expect(dot).toHaveClass("rounded-full", "bg-gain");
    expect(dot).not.toHaveClass("bg-ink-3");
    expect(dot.textContent).toBe("");
    fireEvent.mouseEnter(dot.parentElement as HTMLElement);
    expect(screen.getByRole("tooltip")).toHaveTextContent(/^Enabled$/);
  });

  it("marks a stopped strategy with a quiet grey dot, not the loss colour: off is not a fault (L.12)", () => {
    draw({ enabled: false });

    const dot = screen.getByTestId("card-enabled");
    expect(dot).toHaveAccessibleName(i18n.t("strategies.detail.disabled"));
    expect(dot).toHaveClass("bg-ink-3");
    expect(dot).not.toHaveClass("bg-gain");
    expect(dot).not.toHaveClass("bg-loss");
  });

  it("centres the name and its dot on one line, and lifts the dot above the link for its tooltip (L.10, L.12)", () => {
    const row = draw({ enabled: true });

    const title = within(row).getByRole("link", { name: "Alpha" }).parentElement as HTMLElement;
    expect(title).toContainElement(screen.getByTestId("card-enabled"));
    expect(title).toHaveClass("items-center");
    expect(screen.getByTestId("card-enabled").parentElement).toHaveClass("relative", "z-10");
  });

  it("draws no mark when the card says nothing of whether it runs", () => {
    draw({ enabled: null });

    expect(screen.queryByTestId("card-enabled")).not.toBeInTheDocument();
  });

  it("tags an archived strategy", () => {
    const row = draw({ archived: true });

    expect(within(row).getByText(i18n.t("strategies.row.archived"))).toBeInTheDocument();
  });
});

describe("the whole card opens the strategy", () => {
  it("stretches the one link over the card and leaves that link the only stop", () => {
    const row = draw();

    expect(row).toHaveClass("relative");
    const link = within(row).getByRole("link", { name: "Alpha" });
    expect(link).toHaveClass("after:absolute", "after:inset-0");
    expect(within(row).getAllByRole("link")).toHaveLength(1);
  });

  it("lifts the action above the stretched link so the switch keeps its own click", () => {
    const row = draw({ action: <button type="button">Switch</button> });

    expect((within(row).getByRole("button", { name: "Switch" }).parentElement as HTMLElement)).toHaveClass("relative", "z-10");
  });

  it("lifts the open positions above it too, for their own links", () => {
    const row = draw({ marks: <ul aria-label="marks" /> });

    expect(within(row).getByLabelText("marks").parentElement).toHaveClass("relative", "z-10");
  });

  it("lifts each figure's icon above it, so its tooltip still answers the pointer", () => {
    const row = draw();

    for (const key of FIGURE_ORDER) {
      const term = within(row).getByTestId(`card-${key}`).previousElementSibling as HTMLElement;
      expect(term, key).toHaveClass("relative", "z-10");
    }
  });
});

describe("the figures", () => {
  it("come in one order: age, days active, closed trades, return, deepest, win rate, subscribers, capital", () => {
    const row = draw();

    const order = Array.from(row.querySelectorAll("dd")).map((cell) => cell.getAttribute("data-testid"));
    expect(order).toEqual(FIGURE_ORDER.map((key) => `card-${key}`));
  });

  it("each sit under the icon that names them", () => {
    const row = draw();
    const icons: Record<string, string> = {
      age: "calendar",
      uptime: "clock",
      trades: "list-checks",
      return: "trending-up",
      deepest: "trending-down",
      winrate: "trophy",
      subscribers: "users",
      capital: "wallet",
    };

    for (const [key, icon] of Object.entries(icons)) {
      const term = within(row).getByTestId(`card-${key}`).previousElementSibling as HTMLElement;
      expect(term.querySelector(`svg.lucide-${icon}`), key).not.toBeNull();
      expect(term.textContent, key).toBe("");
    }
  });

  it("keep their words as the icon's name and tooltip, capitalised", () => {
    const row = draw();

    for (const [key, name] of [
      ["age", "Age"],
      ["trades", "Closed trades"],
      ["return", "Return"],
      ["deepest", "Drawdown"],
      ["winrate", "Win rate"],
      ["subscribers", "Live subscribers"],
      ["capital", "Capital"],
    ] as const) {
      const term = within(row).getByTestId(`card-${key}`).previousElementSibling as HTMLElement;
      expect(within(term).getByRole("img", { name }), key).toBeInTheDocument();
    }
    fireEvent.mouseEnter(within(row).getByRole("img", { name: "Drawdown" }).parentElement as HTMLElement);
    expect(within(row).getByRole("tooltip")).toHaveTextContent("Drawdown");
  });

  it("read their values", () => {
    const row = draw();

    expect(within(row).getByTestId("card-trades")).toHaveTextContent(/^3$/);
    expect(within(row).getByTestId("card-return")).toHaveTextContent(/^\+12\.5\s?%$/);
    expect(within(row).getByTestId("card-deepest")).toHaveTextContent(/^[-−]5\.0\s?%$/);
    expect(within(row).getByTestId("card-winrate")).toHaveTextContent(/^60\s?%$/);
    expect(within(row).getByTestId("card-subscribers")).toHaveTextContent(/^2$/);
    expect(within(row).getByTestId("card-capital")).toHaveTextContent(/^1,500\.00 USDT$/);
  });

  it("colour a gain as a gain and a fall as a loss", () => {
    const row = draw();

    expect(within(row).getByTestId("card-return")).toHaveClass("text-gain");
    expect(within(row).getByTestId("card-deepest")).toHaveClass("text-loss");
  });

  it("write a win rate that is not whole to one decimal", () => {
    const row = draw({ figures: { ...FIGURES, winRate: 2 / 3 } });

    expect(within(row).getByTestId("card-winrate")).toHaveTextContent(/^66\.7\s?%$/);
  });

  it("show the dash the capital uses where there is no figure yet", () => {
    const row = draw({
      figures: { ...FIGURES, ret: null, deepest: null, winRate: null, capital: null, subscribers: null },
    });

    for (const key of ["return", "deepest", "winrate", "capital", "subscribers"]) {
      expect(within(row).getByTestId(`card-${key}`), key).toHaveTextContent(/^—$/);
    }
    expect(within(row).getByTestId("card-return")).not.toHaveClass("text-gain", "text-loss");
    expect(within(row).queryByText(/not yet/i)).not.toBeInTheDocument();
  });

  it("show a dash for closed trades that are not known, and a count of none as 0", () => {
    const unknown = draw({ figures: { ...FIGURES, trades: null } });
    expect(within(unknown).getByTestId("card-trades")).toHaveTextContent(/^—$/);
  });

  it("show an ellipsis while a figure is being read", () => {
    const row = draw({ figures: { ...FIGURES, trades: undefined, ret: undefined, deepest: undefined, winRate: undefined } });

    for (const key of ["trades", "return", "deepest", "winrate"]) {
      expect(within(row).getByTestId(`card-${key}`), key).toHaveTextContent(/^…$/);
    }
  });

  it("show an ellipsis for the subscribers and the capital too while they are being read", () => {
    const row = draw({ figures: { ...FIGURES, subscribers: undefined, capital: undefined } });

    expect(within(row).getByTestId("card-subscribers")).toHaveTextContent(/^…$/);
    expect(within(row).getByTestId("card-capital")).toHaveTextContent(/^…$/);
  });

  it("show a dash for a date that cannot be read", () => {
    const row = draw({ since: null });

    expect(within(row).getByTestId("card-age")).toHaveTextContent(/^—$/);
  });

  it("write the age short, from the strategy's creation", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-06T12:00:00Z"));
    const row = draw({ since: "2026-10-27T10:00:00Z" });

    expect(within(row).getByTestId("card-age")).toHaveTextContent(/^10d$/);
  });

  it("count the time subscribed, under its own name, when the card is a seat", () => {
    const row = draw({ sinceKind: "subscribed" });

    const term = within(row).getByTestId("card-age").previousElementSibling as HTMLElement;
    expect(within(term).getByRole("img", { name: "Time subscribed" })).toBeInTheDocument();
    expect(within(term).queryByRole("img", { name: "Age" })).not.toBeInTheDocument();
  });
});

describe("the days active", () => {
  it("count whole days of the uptime, and name them in the tooltip", () => {
    const row = draw();

    expect(within(row).getByTestId("card-uptime")).toHaveTextContent(/^12$/);
    const term = within(row).getByTestId("card-uptime").previousElementSibling as HTMLElement;
    // The tooltip names the figure; the count is the value's.
    expect(within(term).getByRole("img", { name: "Days active" })).toBeInTheDocument();
  });

  it("read as at least when the first activation is only a baseline", () => {
    const row = draw({ uptime: { seconds: 3 * DAY_S, first_enabled_at: "2026-09-29T00:00:00Z", baseline: true } });

    expect(within(row).getByTestId("card-uptime")).toHaveTextContent(/^≥3$/);
    const term = within(row).getByTestId("card-uptime").previousElementSibling as HTMLElement;
    expect(within(term).getByRole("img", { name: "Days active, at least" })).toBeInTheDocument();
  });

  it("make no claim for a strategy never enabled: a dash, and the tooltip says so", () => {
    const row = draw({ uptime: { seconds: 0, first_enabled_at: null, baseline: false } });

    expect(within(row).getByTestId("card-uptime")).toHaveTextContent(/^—$/);
    const term = within(row).getByTestId("card-uptime").previousElementSibling as HTMLElement;
    expect(within(term).getByRole("img", { name: "Never enabled" })).toBeInTheDocument();
  });
});

describe("the grid", () => {
  it("is four icons a row on a phone, centred, and wider from there", () => {
    const row = draw();

    const grid = row.querySelector("dl") as HTMLElement;
    expect(grid).toHaveClass("grid", "grid-cols-4", "place-items-center", "sm:place-items-start", "lg:grid-flow-col", "lg:auto-cols-max", "lg:justify-between");
    // As another author's page spreads them: each column as wide as its value, the first at the left edge, the last
    // at the right, the room left shared out equally between them, so a long PnL takes no room from its neighbours
    // (L.12). Equal columns drew +2058.38 USDT against the return, and away from the closed trades.
    expect(grid).not.toHaveClass("lg:auto-cols-fr");
    expect(grid).not.toHaveClass("lg:auto-cols-[minmax(max-content,1fr)]");
    // The phone's four columns are explicit and would hold the first four at minmax(0, 1fr) on lg.
    expect(grid).toHaveClass("lg:grid-cols-none");
    // From lg every figure stays whole on one line in its column; a phone may wrap it rather than widen the page.
    for (const value of grid.querySelectorAll("dd")) expect(value).toHaveClass("lg:whitespace-nowrap");
  });

  it("keeps each icon centred over the figure it heads", () => {
    const row = draw();

    for (const key of FIGURE_ORDER) {
      expect((within(row).getByTestId(`card-${key}`).parentElement as HTMLElement), key).toHaveClass("w-fit", "items-center");
    }
  });
});

describe("what varies between the lists", () => {
  it("draws a PnL left of the return, a figure like the rest, signed and in its currency (L.11)", () => {
    const row = draw({ pnl: { value: 12.5, currency: "USDT" } });

    const order = Array.from(row.querySelectorAll("dd")).map((cell) => cell.getAttribute("data-testid"));
    expect(order.slice(2, 5)).toEqual(["card-trades", "card-pnl", "card-return"]);
    const pnl = within(row).getByTestId("card-pnl");
    expect(pnl).toHaveTextContent(/^\+12\.50 USDT$/);
    expect(pnl).toHaveClass("text-gain");
    expect(pnl.parentElement).toHaveClass("w-fit", "items-center");
    const term = pnl.previousElementSibling as HTMLElement;
    expect(within(term).getByRole("img", { name: "PnL" })).toBeInTheDocument();
    expect(term).toHaveClass("relative", "z-10");
  });

  it("names a PnL by the label it is given, and reads one still on its way as an ellipsis (L.11)", () => {
    const row = draw({ pnl: { value: undefined, currency: "USDT", label: "Your PnL" } });

    expect(within(row).getByTestId("card-pnl")).toHaveTextContent(/^…$/);
    const term = within(row).getByTestId("card-pnl").previousElementSibling as HTMLElement;
    expect(within(term).getByRole("img", { name: "Your PnL" })).toBeInTheDocument();
  });

  it("counts only the live subscribers, and says so in the tooltip (L.11)", () => {
    const row = draw({ figures: { ...FIGURES, subscribers: 0 } });

    expect(within(row).getByTestId("card-subscribers")).toHaveTextContent(/^0$/);
    fireEvent.mouseEnter(within(row).getByRole("img", { name: "Live subscribers" }).parentElement as HTMLElement);
    expect(within(row).getByRole("tooltip")).toHaveTextContent(/^Live subscribers$/);
  });

  it("draws the trailing figures after the capital", () => {
    const row = draw({ trailing: <Figure label="Share" testId="card-share" value="30%" /> });

    const order = Array.from(row.querySelectorAll("dd")).map((cell) => cell.getAttribute("data-testid"));
    expect(order.slice(-2)).toEqual(["card-capital", "card-share"]);
  });

  it("puts the action on the title's line, at its right end, and leaves the figures the card's whole width (L.12)", () => {
    const row = draw({ action: <button type="button">Switch</button> });

    const button = within(row).getByRole("button", { name: "Switch" });
    const grid = row.querySelector("dl") as HTMLElement;
    expect(grid.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_PRECEDING).not.toBe(0);
    const head = (button.parentElement as HTMLElement).parentElement as HTMLElement;
    expect(head).toContainElement(within(row).getByRole("link", { name: "Alpha" }));
    expect(head).toHaveClass("flex", "justify-between");
    expect(grid.parentElement).toBe(row);
  });

  it("draws a note under the card's figures", () => {
    const row = draw({ notice: <p>Leaving soon</p> });

    expect(within(row).getByText("Leaving soon")).toBeInTheDocument();
  });

  it("replaces the figures it could not read with one alert, and keeps the others", () => {
    const row = draw({ figuresError: "Could not read" });

    expect(within(row).getByRole("alert")).toHaveTextContent("Could not read");
    for (const key of ["trades", "return", "deepest", "winrate"]) {
      expect(within(row).queryByTestId(`card-${key}`), key).not.toBeInTheDocument();
    }
    for (const key of ["age", "uptime", "subscribers", "capital"]) {
      expect(within(row).getByTestId(`card-${key}`), key).toBeInTheDocument();
    }
  });
});
