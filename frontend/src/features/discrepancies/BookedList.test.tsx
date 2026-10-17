import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BookedList } from "@/features/discrepancies/BookedList";
import type { BookedItem } from "@/shared/api/discrepancies";
import i18n from "@/shared/i18n";
import { booking, renderAt, setViewport } from "@/test/harness";

/**
 * The booked-automatically list (spec "The Booked-Automatically List Shows The Last 30 Days And A Booking Is Never
 * Red"; owner decision 66 Q5; prototype examples 7, 10 and 11). The sentences "The last 30 days, newest first, at
 * most 100." and "No booking in the last 30 days." belong to the page's section and are pinned in its test.
 */

const HEADINGS = ["Booked (UTC)", "Pair", "Side", "Quantity", "Strategy", "Fills", "By", "Now"];

const SOL = booking({
  proposal_id: "p-1",
  symbol: "SOLUSDT",
  side: "SELL",
  quantity: "0.5",
  strategy_id: "s-sol",
  strategy_name: "SOL 4h - RSI Divergences",
  fill_count: 1,
  decided_at: "2026-10-16T21:33:00Z",
  discrepancy_open: true,
});
const AAVE = booking({
  proposal_id: "p-2",
  symbol: "AAVEUSDT",
  side: "SELL",
  quantity: "0.82",
  strategy_id: "s-aave",
  strategy_name: "AAVE 4h - RSI Divergences",
  fill_count: 2,
  decided_at: "2026-10-14T03:12:00Z",
});
const SUI = booking({
  proposal_id: "p-3",
  symbol: "SUIUSDT",
  side: "BUY",
  quantity: "140",
  strategy_id: "s-sui",
  strategy_name: "SUI 4h - RSI Divergences",
  fill_count: 1,
  decided_at: "2026-09-29T16:47:00Z",
});
const LINK = booking({
  proposal_id: "p-4",
  exchange: "binance",
  symbol: "LINKUSDT",
  side: "BUY",
  quantity: "12",
  strategy_id: "s-link",
  strategy_name: "LINK 4h - RSI Divergences",
  fill_count: 3,
  decided_at: "2026-10-02T11:05:00Z",
  decided_by: "owner",
});

function mount(items: BookedItem[]) {
  return renderAt(
    <>
      <h2 id="booked-title">Booked automatically</h2>
      <BookedList items={items} labelledBy="booked-title" />
    </>,
  );
}

function cellsOf(row: HTMLElement): string[] {
  return within(row)
    .getAllByRole("cell")
    .map((cell) => (cell.textContent ?? "").replace(/\s+/g, " ").trim());
}

/** The rows of each row group of the table, without the group's own heading row. */
interface TableGroup {
  name: string;
  rows: string[][];
}

function groupsOfTable(): TableGroup[] {
  const table = screen.getByRole("table");
  return [...table.querySelectorAll("tbody")].map((body) => ({
    name: (body.querySelector("th[scope='rowgroup']")?.textContent ?? "").trim(),
    rows: [...body.querySelectorAll("tr")].filter((row) => row.querySelector("td") !== null).map((row) => cellsOf(row)),
  }));
}

afterEach(async () => {
  vi.unstubAllGlobals();
  await i18n.changeLanguage("en");
});

describe("on a wide screen the bookings are a table", () => {
  it("draws the eight headings, named by the section's heading", () => {
    setViewport("wide");
    mount([SOL]);

    const table = screen.getByRole("table", { name: "Booked automatically" });
    const names = within(table)
      .getAllByRole("columnheader")
      .map((heading) => heading.textContent);
    expect(names).toEqual(HEADINGS);
    expect(screen.queryAllByRole("article")).toHaveLength(0);
  });

  it("draws one row group per exchange, newest first within each", () => {
    setViewport("wide");
    mount([SOL, AAVE, SUI, LINK]);

    expect(groupsOfTable().map((group) => [group.name, group.rows.map((row) => row[1])])).toEqual([
      ["BYBIT", ["SOLUSDT", "AAVEUSDT", "SUIUSDT"]],
      ["BINANCE", ["LINKUSDT"]],
    ]);
  });

  it("writes each row's date and time, pair, side, quantity with its base, strategy, fills, by and now", () => {
    setViewport("wide");
    mount([SOL, AAVE, LINK]);

    const [bybit, binance] = groupsOfTable() as [TableGroup, TableGroup];
    expect(bybit.rows[0]).toEqual([
      "10/16/2026 21:33",
      "SOLUSDT",
      "SELL",
      "0.5 SOL",
      "SOL 4h - RSI Divergences",
      "1",
      "automatically",
      "waiting for the next comparison",
    ]);
    expect(bybit.rows[1]).toEqual([
      "10/14/2026 03:12",
      "AAVEUSDT",
      "SELL",
      "0.82 AAVE",
      "AAVE 4h - RSI Divergences",
      "2",
      "automatically",
      "the venue agrees again",
    ]);
    expect(binance.rows[0]).toEqual([
      "10/2/2026 11:05",
      "LINKUSDT",
      "BUY",
      "12 LINK",
      "LINK 4h - RSI Divergences",
      "3",
      "by hand",
      "the venue agrees again",
    ]);
  });

  it("links the strategy's name to its page, and reads a null name as unknown", () => {
    setViewport("wide");
    mount([SOL, booking({ strategy_id: "s-9", strategy_name: null })]);

    expect(screen.getByRole("link", { name: "SOL 4h - RSI Divergences" })).toHaveAttribute("href", "/strategies/s-sol");
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(screen.getByText("unknown strategy")).toBeInTheDocument();
  });

  it("reads 'by hand' for an owner's booking and 'automatically' for the system's", () => {
    setViewport("wide");
    mount([SOL, LINK]);

    const by = groupsOfTable().flatMap((group) => group.rows.map((row) => row[6]));
    expect(by).toEqual(["automatically", "by hand"]);
  });

  it("reads 'waiting for the next comparison' while the discrepancy is open and 'the venue agrees again' once it is not", () => {
    setViewport("wide");
    mount([SOL, AAVE]);

    const now = groupsOfTable().flatMap((group) => group.rows.map((row) => row[7]));
    expect(now).toEqual(["waiting for the next comparison", "the venue agrees again"]);
  });

  it("is never red and never amber", () => {
    setViewport("wide");
    const { container } = mount([SOL, AAVE, LINK]);

    expect(container.querySelector("[class*='loss'], [class*='decision']")).toBeNull();
  });

  it("says the same in Spanish, with the decimal comma and the Spanish headings", async () => {
    await i18n.changeLanguage("es");
    setViewport("wide");
    mount([SOL, LINK]);

    const names = within(screen.getByRole("table"))
      .getAllByRole("columnheader")
      .map((heading) => heading.textContent);
    expect(names).toEqual(["Registrada (UTC)", "Par", "Sentido", "Cantidad", "Estrategia", "Ejecuciones", "Por", "Ahora"]);
    const [bybit, binance] = groupsOfTable() as [TableGroup, TableGroup];
    expect(bybit.rows[0]).toEqual([
      "16/10/2026 21:33",
      "SOLUSDT",
      "SELL",
      "0,5 SOL",
      "SOL 4h - RSI Divergences",
      "1",
      "automáticamente",
      "a la espera de la próxima comparación",
    ]);
    expect(binance.rows[0]?.[6]).toBe("a mano");
    expect(binance.rows[0]?.[7]).toBe("el exchange vuelve a coincidir");
  });
});

describe("on a phone the bookings are cards", () => {
  it("draws one article per booking, named by its pair and side, and no table", () => {
    setViewport("narrow");
    mount([SOL, AAVE, LINK]);

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const cards = screen.getAllByRole("article");
    expect(cards.map((card) => card.getAttribute("aria-label"))).toEqual(["SOLUSDT SELL", "AAVEUSDT SELL", "LINKUSDT BUY"]);
  });

  it("groups the cards under their exchange, newest first", () => {
    setViewport("narrow");
    mount([SOL, AAVE, LINK]);

    const groups = screen.getAllByRole("heading", { level: 3 }).map((heading) => {
      const group = heading.closest("section") as HTMLElement;
      return [heading.textContent, within(group).getAllByRole("article").map((card) => card.getAttribute("aria-label"))];
    });
    expect(groups).toEqual([
      ["bybit", ["SOLUSDT SELL", "AAVEUSDT SELL"]],
      ["binance", ["LINKUSDT BUY"]],
    ]);
  });

  it("carries the same labels and values in a card, with by at its head", () => {
    setViewport("narrow");
    mount([SOL, LINK]);

    const [sol, link] = screen.getAllByRole("article") as [HTMLElement, HTMLElement];
    const valueOf = (card: HTMLElement, label: string) =>
      (within(card).getByText(label, { selector: "dt" }).nextElementSibling?.textContent ?? "").replace(/\s+/g, " ").trim();
    expect(valueOf(sol, "Booked (UTC)")).toBe("10/16/2026 21:33");
    expect(valueOf(sol, "Quantity")).toBe("0.5 SOL");
    expect(valueOf(sol, "Strategy")).toBe("SOL 4h - RSI Divergences");
    expect(valueOf(sol, "Fills")).toBe("1");
    expect(valueOf(sol, "Now")).toBe("waiting for the next comparison");
    expect(within(sol).getByText("automatically")).toBeInTheDocument();
    expect(within(link).getByText("by hand")).toBeInTheDocument();
    expect(within(sol).getByRole("link", { name: "SOL 4h - RSI Divergences" })).toHaveAttribute("href", "/strategies/s-sol");
  });

  it("is never red and never amber", () => {
    setViewport("narrow");
    const { container } = mount([SOL, AAVE, LINK]);

    expect(container.querySelector("[class*='loss'], [class*='decision']")).toBeNull();
  });
});
