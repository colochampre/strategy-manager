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
  subscribers: { count: 3, live: 2 },
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

  it("marks another author's strategy enabled or disabled, in words", () => {
    draw({ enabled: true });

    expect(screen.getByTestId("card-enabled")).toHaveTextContent(i18n.t("strategies.detail.enabled"));
  });

  it("says disabled when it is disabled", () => {
    draw({ enabled: false });

    expect(screen.getByTestId("card-enabled")).toHaveTextContent(i18n.t("strategies.detail.disabled"));
  });

  it("draws a running strategy's word in the gain colour and a stopped one's in the quiet colour", () => {
    draw({ enabled: true });
    expect(screen.getByTestId("card-enabled")).toHaveClass("text-gain");
    expect(screen.getByTestId("card-enabled")).not.toHaveClass("text-ink-3");
  });

  it("draws a stopped strategy's word in the quiet colour", () => {
    draw({ enabled: false });
    expect(screen.getByTestId("card-enabled")).toHaveClass("text-ink-3");
    expect(screen.getByTestId("card-enabled")).not.toHaveClass("text-gain");
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
      winrate: "target",
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
      ["deepest", "Deepest drawdown"],
      ["winrate", "Win rate"],
      ["capital", "Capital"],
    ] as const) {
      const term = within(row).getByTestId(`card-${key}`).previousElementSibling as HTMLElement;
      expect(within(term).getByRole("img", { name }), key).toBeInTheDocument();
    }
    fireEvent.mouseEnter(within(row).getByRole("img", { name: "Deepest drawdown" }).parentElement as HTMLElement);
    expect(within(row).getByRole("tooltip")).toHaveTextContent("Deepest drawdown");
  });

  it("read their values", () => {
    const row = draw();

    expect(within(row).getByTestId("card-trades")).toHaveTextContent(/^3$/);
    expect(within(row).getByTestId("card-return")).toHaveTextContent(/^\+12\.5\s?%$/);
    expect(within(row).getByTestId("card-deepest")).toHaveTextContent(/^[-−]5\.0\s?%$/);
    expect(within(row).getByTestId("card-winrate")).toHaveTextContent(/^60\s?%$/);
    expect(within(row).getByTestId("card-subscribers")).toHaveTextContent(/^3 · 2 live$/);
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
    expect(within(term).getByRole("img", { name: "active 12 days" })).toBeInTheDocument();
  });

  it("read as at least when the first activation is only a baseline", () => {
    const row = draw({ uptime: { seconds: 3 * DAY_S, first_enabled_at: "2026-09-29T00:00:00Z", baseline: true } });

    expect(within(row).getByTestId("card-uptime")).toHaveTextContent(/^≥3$/);
    const term = within(row).getByTestId("card-uptime").previousElementSibling as HTMLElement;
    expect(within(term).getByRole("img", { name: "active at least 3 days" })).toBeInTheDocument();
  });

  it("make no claim for a strategy never enabled: a dash, and the tooltip says so", () => {
    const row = draw({ uptime: { seconds: 0, first_enabled_at: null, baseline: false } });

    expect(within(row).getByTestId("card-uptime")).toHaveTextContent(/^—$/);
    const term = within(row).getByTestId("card-uptime").previousElementSibling as HTMLElement;
    expect(within(term).getByRole("img", { name: i18n.t("strategies.row.neverEnabled") })).toBeInTheDocument();
  });
});

describe("the grid", () => {
  it("is four icons a row on a phone, centred, and wider from there", () => {
    const row = draw();

    const grid = row.querySelector("dl") as HTMLElement;
    expect(grid).toHaveClass("grid", "grid-cols-4", "place-items-center", "sm:place-items-start", "lg:grid-cols-8");
  });

  it("keeps each icon centred over the figure it heads", () => {
    const row = draw();

    for (const key of FIGURE_ORDER) {
      expect((within(row).getByTestId(`card-${key}`).parentElement as HTMLElement), key).toHaveClass("w-fit", "items-center");
    }
  });
});

describe("what varies between the lists", () => {
  it("draws the trailing figures after the capital, and the action last", () => {
    const row = draw({
      trailing: <Figure label="Share" testId="card-share" value="30%" />,
      action: <button type="button">Switch</button>,
    });

    const order = Array.from(row.querySelectorAll("dd")).map((cell) => cell.getAttribute("data-testid"));
    expect(order.slice(-2)).toEqual(["card-capital", "card-share"]);
    const grid = row.querySelector("dl") as HTMLElement;
    const button = within(row).getByRole("button", { name: "Switch" });
    expect(grid.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
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
