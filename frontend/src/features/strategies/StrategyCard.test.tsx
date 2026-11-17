import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StrategyCard } from "@/features/strategies/StrategyCard";
import type { CardFigures, StrategyCardProps } from "@/features/strategies/StrategyCard";
import i18n from "@/shared/i18n";
import { renderAt } from "@/test/harness";

const FIGURES: CardFigures = {
  trades: 3,
  ret: 0.125,
  deepest: -0.05,
  winRate: 0.6,
  profitable: { wins: 3, closed: 5 },
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
        figures={FIGURES}
        {...props}
      />
    </ul>,
  );
  return screen.getByTestId("card-row");
}

/** The groups of a card, in order, with the icon and the label that head each one (owner, 2026-11-17). */
const GROUPS = [
  ["pnl", "coins", "Total PnL"],
  ["drawdown", "trending-down", "Max drawdown"],
  ["profitable", "trophy", "Profitable trades"],
  ["aum", "wallet", "AuM"],
] as const;

/** The test ids of the card's groups, in the order drawn. */
function groupOrder(row: HTMLElement): Array<string | null> {
  return Array.from((row.querySelector("dl") as HTMLElement).children).map((group) => group.getAttribute("data-testid"));
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-17T12:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("what a card names", () => {
  it("names the strategy as a link, its author and its market", () => {
    const row = draw();

    expect(within(row).getByRole("link", { name: "Alpha" })).toHaveAttribute("href", "/strategies/explore/s-1");
    expect(within(row).getByText("by Ana")).toBeInTheDocument();
    expect(within(row).getByTestId("card-market")).toHaveTextContent(/^bybit · usdt-m · USDT/);
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

    expect(within(row).getByRole("button", { name: "Switch" }).parentElement as HTMLElement).toHaveClass("relative", "z-10");
  });

  it("lifts the open positions above it too, for their own links", () => {
    const row = draw({ marks: <ul aria-label="marks" /> });

    expect(within(row).getByLabelText("marks").parentElement).toHaveClass("relative", "z-10");
  });

  it("lifts every icon that names a value above it, so its tooltip still answers the pointer", () => {
    const row = draw({ setup: { share: "30%", leverage: "x3" } });

    for (const name of ["Age", "Live subscribers", "Share", "Leverage"]) {
      expect(within(row).getByRole("img", { name }).parentElement, name).toHaveClass("relative", "z-10");
    }
  });
});

describe("the market line (owner, 2026-11-17)", () => {
  it("dates the strategy from its creation to today, after the market, under a calendar named Age", () => {
    const row = draw();

    const market = within(row).getByTestId("card-market");
    expect(within(market).getByTestId("card-age")).toHaveTextContent(/^Oct 1, 2026 – Nov 17, 2026$/);
    fireEvent.mouseEnter(within(market).getByRole("img", { name: "Age" }).parentElement as HTMLElement);
    expect(within(row).getByRole("tooltip")).toHaveTextContent(/^Age$/);
  });

  it("names the dates the time subscribed when the card is a seat", () => {
    const row = draw({ sinceKind: "subscribed", since: "2026-10-27T10:00:00Z" });

    const market = within(row).getByTestId("card-market");
    expect(within(market).getByTestId("card-age")).toHaveTextContent(/^Oct 27, 2026 – Nov 17, 2026$/);
    expect(within(market).getByRole("img", { name: "Time subscribed" })).toBeInTheDocument();
    expect(within(market).queryByRole("img", { name: "Age" })).not.toBeInTheDocument();
  });

  it("draws no dates from an instant that cannot be read", () => {
    const row = draw({ since: null });

    expect(within(row).queryByTestId("card-age")).not.toBeInTheDocument();
    expect(within(row).getByTestId("card-market")).toHaveTextContent(/^bybit · usdt-m · USDT$/);
  });

  it("draws no days active and no bare count of closed trades", () => {
    const row = draw();

    expect(within(row).queryByTestId("card-uptime")).not.toBeInTheDocument();
    expect(within(row).queryByTestId("card-trades")).not.toBeInTheDocument();
    expect(within(row).queryByRole("img", { name: "Days active" })).not.toBeInTheDocument();
  });
});

describe("the figures", () => {
  it("come in four groups, each under its icon and its label: Total PnL, Max drawdown, Profitable trades, AuM", () => {
    const row = draw();

    expect(groupOrder(row)).toEqual(GROUPS.map(([key]) => `card-group-${key}`));
    for (const [key, icon, label] of GROUPS) {
      const term = within(row).getByTestId(`card-group-${key}`).querySelector("dt") as HTMLElement;
      expect(term.querySelector(`svg.lucide-${icon}`), key).not.toBeNull();
      expect(term, key).toHaveTextContent(label);
    }
  });

  it("read their values", () => {
    const row = draw();

    expect(within(row).getByTestId("card-return")).toHaveTextContent(/^\+12\.5\s?%$/);
    expect(within(row).getByTestId("card-deepest")).toHaveTextContent(/^[-−]5\.0\s?%$/);
    expect(within(row).getByTestId("card-winrate")).toHaveTextContent(/^60\s?%$/);
    expect(within(row).getByTestId("card-wins")).toHaveTextContent(/^3\/5$/);
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

  it("show the dash where there is no figure yet, and no count of wins", () => {
    const row = draw({
      figures: { ...FIGURES, ret: null, deepest: null, winRate: null, profitable: null, capital: null, subscribers: null },
    });

    for (const key of ["return", "deepest", "winrate", "capital", "subscribers"]) {
      expect(within(row).getByTestId(`card-${key}`), key).toHaveTextContent(/^—$/);
    }
    expect(within(row).getByTestId("card-return")).not.toHaveClass("text-gain", "text-loss");
    expect(within(row).queryByTestId("card-wins")).not.toBeInTheDocument();
  });

  it("show an ellipsis while a figure is being read", () => {
    const row = draw({
      figures: {
        ...FIGURES,
        ret: undefined,
        deepest: undefined,
        winRate: undefined,
        profitable: undefined,
        subscribers: undefined,
        capital: undefined,
      },
    });

    for (const key of ["return", "deepest", "winrate", "subscribers", "capital"]) {
      expect(within(row).getByTestId(`card-${key}`), key).toHaveTextContent(/^…$/);
    }
  });

  it("counts only the live subscribers under AuM, and says so in the icon's tooltip", () => {
    const row = draw({ figures: { ...FIGURES, subscribers: 0 } });

    const aum = within(row).getByTestId("card-group-aum");
    expect(within(aum).getByTestId("card-subscribers")).toHaveTextContent(/^0$/);
    fireEvent.mouseEnter(within(aum).getByRole("img", { name: "Live subscribers" }).parentElement as HTMLElement);
    expect(within(row).getByRole("tooltip")).toHaveTextContent(/^Live subscribers$/);
  });

  it("lays the groups out in equal columns, one row from lg, two a row on a phone and three from sm", () => {
    const row = draw();

    const grid = row.querySelector("dl") as HTMLElement;
    expect(grid).toHaveClass("grid", "grid-cols-2", "sm:grid-cols-3", "lg:grid-flow-col", "lg:grid-cols-none", "lg:auto-cols-fr");
  });
});

describe("what varies between the lists", () => {
  it("draws a PnL before the return under Total PnL, signed and in its currency", () => {
    const row = draw({ pnl: { value: 12.5, currency: "USDT" } });

    const group = within(row).getByTestId("card-group-pnl");
    const values = Array.from((group.querySelector("dd") as HTMLElement).children).map((value) => value.getAttribute("data-testid"));
    expect(values).toEqual(["card-pnl", "card-return"]);
    const pnl = within(group).getByTestId("card-pnl");
    expect(pnl).toHaveTextContent(/^\+12\.50 USDT$/);
    expect(pnl).toHaveClass("text-gain");
  });

  it("reads a PnL still on its way as an ellipsis", () => {
    const row = draw({ pnl: { value: undefined, currency: "USDT" } });

    expect(within(row).getByTestId("card-pnl")).toHaveTextContent(/^…$/);
  });

  it("draws no PnL where the list has none to show, the return alone under Total PnL", () => {
    const row = draw();

    expect(within(row).queryByTestId("card-pnl")).not.toBeInTheDocument();
    expect(within(within(row).getByTestId("card-group-pnl")).getByTestId("card-return")).toBeInTheDocument();
  });

  it("draws a seat's settings last, its share and its leverage each beside a named icon", () => {
    const row = draw({ setup: { share: "30%", leverage: "x3" } });

    expect(groupOrder(row).at(-1)).toBe("card-group-setup");
    const setup = within(row).getByTestId("card-group-setup");
    expect(setup.querySelector("dt")).toHaveTextContent("Settings");
    expect(within(setup).getByTestId("card-share")).toHaveTextContent(/^30%$/);
    expect(within(setup).getByTestId("card-leverage")).toHaveTextContent(/^x3$/);
    expect(within(setup).getByRole("img", { name: "Share" })).toBeInTheDocument();
    expect(within(setup).getByRole("img", { name: "Leverage" })).toBeInTheDocument();
  });

  it("draws no settings where the card is not a seat", () => {
    const row = draw();

    expect(within(row).queryByTestId("card-group-setup")).not.toBeInTheDocument();
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

  it("replaces the figures it could not read with one alert, and keeps AuM, the settings and the dates", () => {
    const row = draw({ figuresError: "Could not read", setup: { share: "30%", leverage: "x3" } });

    expect(within(row).getByRole("alert")).toHaveTextContent("Could not read");
    for (const key of ["group-pnl", "group-drawdown", "group-profitable"]) {
      expect(within(row).queryByTestId(`card-${key}`), key).not.toBeInTheDocument();
    }
    for (const key of ["group-aum", "group-setup", "age"]) {
      expect(within(row).getByTestId(`card-${key}`), key).toBeInTheDocument();
    }
  });
});
