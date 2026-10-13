import { act, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OpenPositionsSection } from "@/features/positions/OpenPositionsSection";
import type { OpenPosition } from "@/shared/api/positions";
import type { Strategy } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import { lock, openPosition, openState, renderAt, stubApi, unlock } from "@/test/harness";
import type { OpenPositionsStub } from "@/test/harness";

/**
 * T10, the detail section: the table, its cells, its sub-rows, its notes, its states and its orders, and the
 * phone cards (design addendum § H, examples 13 to 21, 25d, 25e and 26b).
 */

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const ALPHA = "11111111-1111-4111-8111-111111111111";

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: ALPHA,
    name: "Alpha",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    allocation_percent: "100",
    enabled: true,
    archived_at: null,
    allowed_pairs: ["SOLUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    ...overrides,
  };
}

beforeEach(async () => {
  unlock();
  await act(() => i18n.changeLanguage("en"));
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

/** Lets the stubbed answers reach the components. */
async function settle() {
  for (let turn = 0; turn < 3; turn += 1) await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
}

const answering = (...args: Parameters<typeof openState>): OpenPositionsStub => ({ kind: "ok", body: openState(...args) });

async function mountSection(openPositions: OpenPositionsStub, subject = strategy(), bookings: unknown[] = []) {
  const api = stubApi(HEALTH, bookings, undefined, {}, undefined, {}, undefined, openPositions);
  const view = renderAt(<OpenPositionsSection strategy={subject} />);
  await settle();
  return { api, view };
}

/** The table, asserted to exist before it is returned, so that its absence is a failed assertion. */
function theTable(): HTMLElement {
  expect(screen.queryByRole("table")).toBeInTheDocument();
  return screen.getByRole("table");
}

/** The rows of the table that are positions (eight cells), not sub-rows (one cell across the eight). */
function positionRows(table: HTMLElement): HTMLElement[] {
  return within(table)
    .getAllByRole("row")
    .filter((row) => row.querySelectorAll("td").length === 8);
}

function cellsOf(row: HTMLElement): HTMLElement[] {
  return [...row.querySelectorAll<HTMLElement>("td")];
}

const COLUMN = { opened: 0, pair: 1, side: 2, size: 3, entry: 4, fees: 5, margin: 6, leverage: 7 } as const;

/** The one position row of a table that holds one, and its cells. */
function onlyRow(): HTMLElement[] {
  const rows = positionRows(theTable());
  expect(rows).toHaveLength(1);
  return cellsOf(rows[0] as HTMLElement);
}

/** A position the facts could not decorate: every nullable field is null (design § F). */
function noFacts(overrides: Partial<OpenPosition> = {}): OpenPosition {
  return openPosition({
    strategy_id: ALPHA,
    markets: ["STXUSDT"],
    origin: "live",
    figures_missing: "NO_FACTS",
    side: null,
    base_currency: null,
    size: null,
    opened_size: null,
    entry_price: null,
    opened_at: null,
    fill_count: 0,
    fees: null,
    margin_granted: null,
    leverage: null,
    reservation_status: null,
    ...overrides,
  });
}

describe("an absent figure is a dash with its reason (T10, the first red of op.3)", () => {
  it("draws a dash named 'not recorded' for a null leverage on a position that has its facts, and never 1x", async () => {
    await mountSection(answering([openPosition({ strategy_id: ALPHA, leverage: null })]));

    const cell = onlyRow()[COLUMN.leverage] as HTMLElement;
    expect(cell).toHaveTextContent("not recorded");
    expect(cell).not.toHaveTextContent("1x");
    expect(cell.textContent).toBe("—not recorded");
    expect(within(cell).getByText("—")).toHaveAttribute("aria-hidden", "true");
    expect(within(cell).getByText("not recorded")).toHaveClass("sr-only");
  });

  it("draws 'figures not readable' in EVERY empty cell of a position the facts could not decorate", async () => {
    await mountSection(answering([noFacts()]));

    const cells = onlyRow();
    for (const column of ["opened", "side", "size", "entry", "fees", "margin", "leverage"] as const) {
      expect(cells[COLUMN[column]]?.textContent, column).toBe("—figures not readable");
    }
    expect(cells[COLUMN.pair]).toHaveTextContent("STXUSDT");
  });

  it("draws the Opened cell of a null as a dash, never 'Invalid Date' and never an 'x' alone", async () => {
    await mountSection(answering([noFacts()]));

    const cells = onlyRow();
    const text = cells.map((cell) => cell.textContent).join("|");
    expect(text).not.toContain("Invalid Date");
    expect(text).not.toMatch(/(^|\|)x/);
    expect(cells[COLUMN.opened]?.textContent).toBe("—figures not readable");
    expect(cells[COLUMN.leverage]?.textContent).not.toContain("x");
  });

  it("keeps 'not recorded' for the leverage of a position with facts and writes the facts it has", async () => {
    await mountSection(
      answering([openPosition({ strategy_id: ALPHA, leverage: null, fees: "0.17", margin_granted: "121.8" })]),
    );

    const cells = onlyRow();
    expect(cells[COLUMN.leverage]?.textContent).toBe("—not recorded");
    expect(cells[COLUMN.fees]).toHaveTextContent("0.17");
    expect(cells[COLUMN.margin]).toHaveTextContent("121.8");
  });
});
