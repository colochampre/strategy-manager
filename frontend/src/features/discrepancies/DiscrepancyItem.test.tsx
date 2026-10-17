import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DiscrepancyItem } from "@/features/discrepancies/DiscrepancyItem";
import type { DiscrepancyVariant } from "@/features/discrepancies/DiscrepancyItem";
import type { ConfirmedDiscrepancy } from "@/shared/api/discrepancies";
import i18n from "@/shared/i18n";
import { discrepancy, renderAt } from "@/test/harness";

/**
 * One discrepancy item (spec "A Needs-You Item Says What Is Wrong In Red, With Its Words, And What The Owner Can
 * Do" and "A Being-Booked Item Is Neutral And Says So"; owner decision 66 Q3, Q6 and Q9; prototype examples 5, 6,
 * 8c, 10 and 11).
 */

const READ_AT = "2026-10-16T21:40:03Z";
const MANUAL = "Ask for a manual reconciliation. Nothing in this panel can book it.";
const BY_HAND = "Close it on the exchange by hand. The next comparison resolves it.";

function mount(item: ConfirmedDiscrepancy, variant: DiscrepancyVariant = "needsYou") {
  renderAt(<DiscrepancyItem item={item} variant={variant} readAt={READ_AT} />);
  return screen.getByRole("article");
}

/** The value written beside a label of a description list, whatever the markup between them. */
function valueOf(article: HTMLElement, label: string): HTMLElement {
  const term = within(article).getByText(label, { selector: "dt" });
  return term.nextElementSibling as HTMLElement;
}

afterEach(async () => {
  await i18n.changeLanguage("en");
});

describe("the sentence of each reason", () => {
  it.each([
    {
      name: "NOT_BOOKED on a full close",
      item: discrepancy({ reason: "NOT_BOOKED", kind: "ATTRIBUTABLE_FULL_CLOSE" }),
      red: "Could not be booked automatically.",
      under: "The venue closed a position the ledger holds open.",
      action: MANUAL,
    },
    {
      name: "NOT_BOOKED on a reduction only one strategy holds (note N4)",
      item: discrepancy({ reason: "NOT_BOOKED", kind: "ATTRIBUTABLE_SINGLE_ALLOCATION" }),
      red: "Could not be booked automatically.",
      under: "The venue reduced a position only one strategy holds.",
      action: MANUAL,
    },
    {
      name: "SEVERAL_ALLOCATIONS",
      item: discrepancy({ reason: "SEVERAL_ALLOCATIONS", kind: "ATTRIBUTABLE_FULL_CLOSE" }),
      red: "The venue closed a position several strategies share; one booking cannot split it.",
      under: null,
      action: MANUAL,
    },
    {
      name: "AMBIGUOUS_PARTIAL_REDUCE, which has no reason",
      item: discrepancy({ reason: null, kind: "AMBIGUOUS_PARTIAL_REDUCE" }),
      red: "The venue reduced a position several strategies share; which one cannot be told.",
      under: null,
      action: MANUAL,
    },
    {
      name: "NOT_BOOKABLE, whose red sentence is the kind's",
      item: discrepancy({ reason: "NOT_BOOKABLE", kind: "AMBIGUOUS_PARTIAL_REDUCE" }),
      red: "The venue reduced a position several strategies share; which one cannot be told.",
      under: null,
      action: MANUAL,
    },
    {
      name: "NO_MATCHING_ALLOCATION",
      item: discrepancy({ reason: null, kind: "NO_MATCHING_ALLOCATION", allocations: [] }),
      red: "The venue holds a position no strategy opened.",
      under: null,
      action: BY_HAND,
    },
  ])("writes $name in red, with what the owner can do", ({ item, red, under, action }) => {
    const article = mount(item);

    const sentence = within(article).getByText(red);
    expect(sentence).toHaveClass("text-loss");
    if (under !== null) {
      const kind = within(article).getByText(under);
      expect(kind).not.toHaveClass("text-loss");
    }
    expect(valueOf(article, "What you can do")).toHaveTextContent(action);
    // Only one of the two actions is ever offered.
    expect(within(article).queryByText(action === MANUAL ? BY_HAND : MANUAL)).not.toBeInTheDocument();
  });

  it("does not say the kind twice when the red sentence already is the kind", () => {
    const article = mount(discrepancy({ reason: null, kind: "NO_MATCHING_ALLOCATION", allocations: [] }));

    expect(within(article).getAllByText("The venue holds a position no strategy opened.")).toHaveLength(1);
  });

  it("draws a red border on a Needs-you item, and the sentence is text, not a colour alone", () => {
    const article = mount(discrepancy());

    expect(article).toHaveClass("border-loss");
    expect(article).not.toHaveClass("border-rule");
    expect(article).toHaveTextContent("Could not be booked automatically.");
  });

  it("says the same in Spanish, to usted", async () => {
    await i18n.changeLanguage("es");
    const article = mount(discrepancy({ reason: "NOT_BOOKED" }));

    expect(within(article).getByText("No se pudo registrar automáticamente.")).toHaveClass("text-loss");
    expect(within(article).getByText("El exchange cerró una posición que el libro mayor tiene abierta.")).toBeInTheDocument();
    expect(valueOf(article, "Qué puede hacer")).toHaveTextContent("Pida una conciliación manual. Nada en este panel puede registrarla.");
  });
});

describe("the nets and the signed difference", () => {
  it.each([
    ["a ledger of 0.5 SOL and an exchange of 0", "SOLUSDT", "0", "0.5", "0 SOL", "0.5 SOL", "-0.5 SOL"],
    ["an exchange of 12 LINK and an empty ledger", "LINKUSDT", "12", "0", "12 LINK", "0 LINK", "+12 LINK"],
    ["a partial reduction", "AAVEUSDT", "0.5", "1.32", "0.5 AAVE", "1.32 AAVE", "-0.82 AAVE"],
    ["fractions a binary float would get wrong", "STXUSDT", "0.1", "0.3", "0.1 STX", "0.3 STX", "-0.2 STX"],
    ["a large ledger", "STXUSDT", "0", "450", "0 STX", "450 STX", "-450 STX"],
  ])("reads Exchange, Ledger and Difference for %s", (_name, symbol, venue, ledger, exchangeText, ledgerText, difference) => {
    const article = mount(discrepancy({ symbol, venue_net_base: venue, ledger_net_base: ledger }));

    expect(valueOf(article, "Exchange")).toHaveTextContent(exchangeText);
    expect(valueOf(article, "Ledger")).toHaveTextContent(ledgerText);
    expect(valueOf(article, "Difference")).toHaveTextContent(difference);
  });

  it("writes the figures with the decimal comma in Spanish, under the Spanish labels", async () => {
    await i18n.changeLanguage("es");
    const article = mount(discrepancy({ symbol: "AAVEUSDT", venue_net_base: "0.5", ledger_net_base: "1.32" }));

    expect(valueOf(article, "Exchange")).toHaveTextContent("0,5 AAVE");
    expect(valueOf(article, "Libro mayor")).toHaveTextContent("1,32 AAVE");
    expect(valueOf(article, "Diferencia")).toHaveTextContent("-0,82 AAVE");
  });

  it("draws the three nets in a row, and on a phone two over one with the difference on its own row", () => {
    const article = mount(discrepancy());

    const nets = valueOf(article, "Exchange").parentElement?.parentElement as HTMLElement;
    expect(nets).toHaveClass("grid", "grid-cols-2", "sm:grid-cols-3");
    expect(valueOf(article, "Difference").parentElement).toHaveClass("col-span-2", "sm:col-span-1");
    expect(valueOf(article, "Exchange").parentElement).not.toHaveClass("col-span-2");
    expect(valueOf(article, "Ledger").parentElement).not.toHaveClass("col-span-2");
  });
});

describe("the pair, the pool and the times", () => {
  it("names the item by its pair, with the pool beside it", () => {
    const article = mount(discrepancy({ symbol: "SOLUSDT", venue: "usdt-m", settlement_currency: "USDT" }));

    const heading = within(article).getByRole("heading", { name: "SOLUSDT" });
    expect(article).toHaveAccessibleName("SOLUSDT");
    expect(heading).toBeInTheDocument();
    expect(within(article).getByText("usdt-m · USDT")).toBeInTheDocument();
  });

  it("carries the id the hash names", () => {
    const article = mount(discrepancy({ discrepancy_id: "41" }));

    expect(article).toHaveAttribute("id", "discrepancy-41");
  });

  it("writes Confirmed with date and time in UTC and Last compared with the time", () => {
    const article = mount(discrepancy({ confirmed_at: "2026-10-16T21:31:00Z", last_observed_at: "2026-10-16T21:39:42Z" }));

    expect(valueOf(article, "Confirmed")).toHaveTextContent("10/16/2026 21:31 UTC");
    expect(valueOf(article, "Last compared")).toHaveTextContent(/^21:39:42 UTC$/);
  });

  it("puts the date before a last comparison on another UTC day than the read", () => {
    const article = mount(discrepancy({ last_observed_at: "2026-10-15T23:59:42Z" }));

    expect(valueOf(article, "Last compared")).toHaveTextContent("10/15/2026 23:59:42 UTC");
  });

  it("writes the date in day-first order in Spanish", async () => {
    await i18n.changeLanguage("es");
    const article = mount(discrepancy({ confirmed_at: "2026-10-16T21:31:00Z" }));

    expect(valueOf(article, "Confirmada")).toHaveTextContent("16/10/2026 21:31 UTC");
    expect(valueOf(article, "Última comparación")).toHaveTextContent("21:39:42 UTC");
  });

  it("draws no Confirmed row for an item with no confirmation time, rather than an invented one", () => {
    const article = mount(discrepancy({ confirmed_at: null }));

    expect(within(article).queryByText("Confirmed", { selector: "dt" })).not.toBeInTheDocument();
    expect(within(article).getByText("Last compared", { selector: "dt" })).toBeInTheDocument();
  });
});

describe("the strategies", () => {
  it("labels one strategy 'Strategy' and links its name to its page", () => {
    const article = mount(
      discrepancy({ allocations: [{ allocation_id: "a-1", strategy_id: "s-1", strategy_name: "SOL 4h - RSI Divergences" }] }),
    );

    expect(within(article).getByText("Strategy", { selector: "dt" })).toBeInTheDocument();
    expect(within(article).queryByText("Strategies", { selector: "dt" })).not.toBeInTheDocument();
    const link = within(article).getByRole("link", { name: "SOL 4h - RSI Divergences" });
    expect(link).toHaveAttribute("href", "/strategies/s-1");
  });

  it("labels several 'Strategies' and links each name", () => {
    const article = mount(
      discrepancy({
        reason: "SEVERAL_ALLOCATIONS",
        allocations: [
          { allocation_id: "a-1", strategy_id: "s-1", strategy_name: "STX 4h - RSI Divergences" },
          { allocation_id: "a-2", strategy_id: "s-2", strategy_name: "STX 1h - Breakout" },
        ],
      }),
    );

    expect(within(article).getByText("Strategies", { selector: "dt" })).toBeInTheDocument();
    const links = within(article).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(["STX 4h - RSI Divergences", "STX 1h - Breakout"]);
    expect(links.map((link) => link.getAttribute("href"))).toEqual(["/strategies/s-1", "/strategies/s-2"]);
  });

  it("names the strategies in Spanish with the Spanish labels", async () => {
    await i18n.changeLanguage("es");
    const article = mount(discrepancy({ reason: null, kind: "NO_MATCHING_ALLOCATION", allocations: [] }));

    expect(valueOf(article, "Estrategia")).toHaveTextContent("Ninguna estrategia");
  });

  it("reads 'No strategy' for an item with no allocation, and links nothing", () => {
    const article = mount(discrepancy({ reason: null, kind: "NO_MATCHING_ALLOCATION", allocations: [] }));

    expect(valueOf(article, "Strategy")).toHaveTextContent("No strategy");
    expect(within(article).queryByRole("link")).not.toBeInTheDocument();
  });

  it("reads a null strategy name as 'unknown strategy' and does not link it to nothing (K row 13)", () => {
    const article = mount(discrepancy({ allocations: [{ allocation_id: "a-1", strategy_id: "s-1", strategy_name: null }] }));

    expect(valueOf(article, "Strategy")).toHaveTextContent("unknown strategy");
    expect(within(article).queryByRole("link")).not.toBeInTheDocument();
  });

  it("keeps the named strategy linked beside an unknown one", () => {
    const article = mount(
      discrepancy({
        allocations: [
          { allocation_id: "a-1", strategy_id: "s-1", strategy_name: "Alpha" },
          { allocation_id: "a-2", strategy_id: "s-2", strategy_name: null },
        ],
      }),
    );

    expect(within(article).getAllByRole("link").map((link) => link.textContent)).toEqual(["Alpha"]);
    expect(valueOf(article, "Strategies")).toHaveTextContent("Alpha, unknown strategy");
  });
});

describe("an item being booked", () => {
  it("is neutral, says it is being booked, and offers nothing to do", () => {
    const article = mount(discrepancy({ reason: null, kind: "ATTRIBUTABLE_SINGLE_ALLOCATION" }), "beingBooked");

    expect(article).toHaveClass("border-rule");
    expect(article).not.toHaveClass("border-loss");
    const sentence = within(article).getByText("Being booked automatically.");
    expect(sentence).not.toHaveClass("text-loss");
    expect(within(article).getByText("The venue reduced a position only one strategy holds.")).toBeInTheDocument();
    expect(within(article).queryByText("What you can do")).not.toBeInTheDocument();
    expect(within(article).queryByText(MANUAL)).not.toBeInTheDocument();
    expect(article.querySelector(".text-loss, .border-loss, .bg-loss")).toBeNull();
  });

  it("still shows the pair, the nets and the strategy, and carries its id for the hash", () => {
    const article = mount(discrepancy({ discrepancy_id: "47" }), "beingBooked");

    expect(article).toHaveAttribute("id", "discrepancy-47");
    expect(within(article).getByRole("heading", { name: "SOLUSDT" })).toBeInTheDocument();
    expect(valueOf(article, "Difference")).toHaveTextContent("-0.5 SOL");
    expect(within(article).getByRole("link", { name: "Alpha" })).toBeInTheDocument();
  });

  it("ignores a reason it may carry: it says 'Being booked automatically.' and not the refusal", () => {
    const article = mount(discrepancy({ reason: "NOT_BOOKED" }), "beingBooked");

    expect(within(article).getByText("Being booked automatically.")).toBeInTheDocument();
    expect(within(article).queryByText("Could not be booked automatically.")).not.toBeInTheDocument();
  });
});
