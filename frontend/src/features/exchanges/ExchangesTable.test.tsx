import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ExchangesPage } from "@/features/exchanges/ExchangesPage";
import i18n from "@/shared/i18n";
import { emptyKey, lock, pool, resetExchangeScope, storedKey, stubApi, unlock } from "@/test/harness";

/**
 * Vincular exchange as the prototype's ex6 draws it (L12): the dashed action across the top, the one-key line
 * under it, and the "Linked" card with the filter, the total pill and a table of the keys.
 */

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
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

function mount(rows: unknown[], pools: unknown[] = [pool("bybit")]) {
  stubApi(HEALTH, [], { kind: "ok", body: pools }, {}, undefined, {}, { kind: "ok", body: rows });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/exchanges"]}>
        <ExchangesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function table(): Promise<HTMLElement> {
  return screen.findByRole("table");
}

/** The cells of the row of an exchange, in column order, by the heading of its first cell. */
async function rowOf(name: string): Promise<HTMLElement[]> {
  const grid = await table();
  const heading = within(grid).getByRole("heading", { level: 3, name });
  return within(heading.closest("tr") as HTMLElement).getAllByRole("cell", { hidden: false });
}

describe("the action across the top (ex6 .bar-btn)", () => {
  it("is a full-width dashed button, 44 px, centred, on panel-2, with the plus in gain and the words", async () => {
    mount([storedKey("bybit")]);

    const button = await screen.findByRole("button", { name: "Link exchange" });
    expect(button).toHaveClass(
      "flex",
      "w-full",
      "h-11",
      "justify-center",
      "rounded-lg",
      "border",
      "border-dashed",
      "border-rule-strong",
      "bg-panel-2",
      "font-medium",
    );
    expect(button.querySelector("svg")).toHaveClass("text-gain");
    expect(button).not.toHaveClass("bg-gain");
  });

  it("is followed by the one-key line, then by the Linked card", async () => {
    mount([storedKey("bybit")]);

    const button = await screen.findByRole("button", { name: "Link exchange" });
    const help = screen.getByText("One key is kept per exchange. Saving a new one replaces the previous one.");
    const card = screen.getByRole("heading", { level: 2, name: "Linked" });
    expect(button.compareDocumentPosition(help) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(help.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(help).toHaveClass("text-[13px]", "text-ink-2");
  });

  it("writes the line in Spanish as the prototype does", async () => {
    await i18n.changeLanguage("es");
    mount([storedKey("bybit")]);

    expect(
      await screen.findByText("Se conserva una sola clave por exchange. Al guardar una nueva, reemplaza a la anterior."),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Vinculadas" })).toBeInTheDocument();
  });
});

describe("the Linked card (ex6 .card, .inp, .total, .chip-n)", () => {
  it("holds a rounded filter with its search icon and the total as a pill reading `n records`", async () => {
    mount([storedKey("bybit"), storedKey("binance")], [pool("bybit"), pool("binance")]);

    const filter = await screen.findByRole("searchbox", { name: "Filter exchanges" });
    expect(filter).toHaveClass("h-[38px]", "w-full", "rounded-full", "border-rule", "bg-ground", "pl-4");
    expect(filter.parentElement?.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    const pill = screen.getByText("2 records");
    expect(pill).toHaveClass("rounded-md", "border-rule", "bg-ground", "text-[12.5px]");
    expect(pill.parentElement).toHaveTextContent("Total 2 records");
  });

  it("says `1 record` in the singular", async () => {
    mount([storedKey("bybit")], [pool("bybit")]);

    expect(await screen.findByText("1 record")).toBeInTheDocument();
  });

  it("draws the table in a bordered, rounded frame that scrolls sideways on its own", async () => {
    mount([storedKey("bybit")]);

    const grid = await table();
    const frame = grid.parentElement as HTMLElement;
    expect(frame).toHaveClass("overflow-x-auto", "rounded-lg", "border", "border-rule");
  });

  it("has the six columns of the prototype, on the ground colour, 12.5 px, in ink-3", async () => {
    mount([storedKey("bybit")]);

    const grid = await table();
    const heads = within(grid).getAllByRole("columnheader");
    expect(heads.map((head) => head.textContent)).toEqual([
      "Exchange",
      "Key",
      "Permissions",
      "Status",
      "Linked on",
      "Actions",
    ]);
    for (const head of heads) expect(head).toHaveClass("bg-ground", "text-[12.5px]", "text-ink-3", "font-medium");
    expect(heads[5]).toHaveClass("text-right");
  });

  it("writes the columns in Spanish", async () => {
    await i18n.changeLanguage("es");
    mount([storedKey("bybit")]);

    const grid = await table();
    expect(within(grid).getAllByRole("columnheader").map((head) => head.textContent)).toEqual([
      "Exchange",
      "Clave",
      "Permisos",
      "Estado",
      "Vinculada el",
      "Acciones",
    ]);
  });
});

describe("a row of a stored key (ex6 tbody tr)", () => {
  it("says the wordmark, the last four in mono, `Trading` in gain, `Active` with a dot, and the day as dd/mm/yyyy", async () => {
    mount([storedKey("bybit", { last4: "7Q2k", stored_at: "2026-09-03T10:00:00Z", trade_capable: true })]);

    const cells = await rowOf("Bybit");

    expect(cells).toHaveLength(6);
    expect(cells[1]).toHaveTextContent("••••7Q2k");
    expect(cells[1]?.querySelector(".font-mono")).not.toBeNull();
    const trading = within(cells[2] as HTMLElement).getByText("Trading");
    expect(trading).toHaveClass("h-6", "rounded-xl", "border", "text-xs", "font-medium", "bg-gain/14", "text-gain-bright");
    const active = within(cells[3] as HTMLElement).getByText("Active");
    expect(active).toHaveClass("h-6", "rounded-xl", "bg-gain/14");
    expect(active.querySelector('[data-dot="true"]')).toHaveClass("bg-gain", "rounded-full");
    expect(cells[4]).toHaveTextContent("03/09/2026");
    expect(cells[4]).toHaveClass("font-mono");
  });

  it("says `Read-only` as a neutral pill for a key that cannot trade, keeps the amber mark, and has no warning sentence under the row (L13)", async () => {
    mount([storedKey("bybit", { trade_capable: false })]);

    const cells = await rowOf("Bybit");

    const pill = within(cells[2] as HTMLElement).getByText("Read-only");
    expect(pill).toHaveClass("h-6", "rounded-xl", "bg-ink-2/11", "text-ink-2");
    expect(pill.outerHTML).not.toMatch(AMBER);
    // The shared mark stays, in amber: the owner has something to do. Its sentence is gone.
    const group = (await screen.findByRole("heading", { level: 3, name: "Bybit" })).closest("tbody") as HTMLElement;
    expect(within(group).getByText("read-only").outerHTML).toMatch(AMBER);
    expect(within(group).queryByText(/This key cannot trade/)).not.toBeInTheDocument();
  });

  it("gives the row two icon buttons, 32 px, named by their exchange: replace the key and delete it", async () => {
    mount([storedKey("bybit")]);

    const cells = await rowOf("Bybit");
    const actions = cells[5] as HTMLElement;

    expect(actions).toHaveClass("text-right");
    const replace = within(actions).getByRole("button", { name: "Replace key Bybit" });
    const remove = await waitFor(() => within(actions).getByRole("button", { name: "Delete key Bybit" }));
    for (const button of [replace, remove]) {
      expect(button).toHaveClass("size-8", "rounded-lg", "border");
      expect(button.textContent).toBe("");
      expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    }
    expect(replace).toHaveClass("border-rule", "text-ink-2");
    expect(remove).toHaveClass("border-loss", "text-loss", "hover:bg-loss/10");
  });
});

describe("a keyless exchange with a pool on (the case that needs the owner's decision)", () => {
  it("stays a row: no key and no day, an amber `no key` pill as its state, no sentence under it (L13), and `Add key`", async () => {
    mount([storedKey("bybit"), emptyKey("binance")], [pool("bybit"), pool("binance")]);

    const cells = await rowOf("Binance");

    expect(cells[1]).toHaveTextContent("—");
    expect(cells[2]).toHaveTextContent("—");
    expect(cells[4]).toHaveTextContent("—");
    const state = within(cells[3] as HTMLElement).getByText("no key");
    expect(state.outerHTML).toMatch(AMBER);
    expect(state).toHaveClass("h-6", "rounded-xl");
    const group = (await screen.findByRole("heading", { level: 3, name: "Binance" })).closest("tbody") as HTMLElement;
    expect(within(group).queryByText(/No key stored/)).not.toBeInTheDocument();
    expect(within(cells[5] as HTMLElement).getByRole("button", { name: "Add key Binance" })).toBeInTheDocument();
    // With nothing to say under it, the row has no detail row at all.
    expect(group.querySelectorAll("tr")).toHaveLength(1);
  });
});

describe("the form of a row (ex6: an expanded row)", () => {
  it("opens in a row of its own under the key, spanning all six columns", async () => {
    mount([storedKey("bybit")]);
    const cells = await rowOf("Bybit");

    fireEvent.click(within(cells[5] as HTMLElement).getByRole("button", { name: "Replace key Bybit" }));

    const form = await screen.findByLabelText("API key");
    const cell = form.closest("td") as HTMLElement;
    expect(cell).toHaveAttribute("colspan", "6");
    const keyRow = (cells[0] as HTMLElement).closest("tr") as HTMLElement;
    expect(keyRow.compareDocumentPosition(cell) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(cell.closest("tbody")).toBe(keyRow.closest("tbody"));
  });

  it("opens the form of a new exchange under the dashed button, not in the table", async () => {
    mount([storedKey("bybit")], [pool("bybit")]);

    fireEvent.click(await screen.findByRole("button", { name: "Link exchange" }));
    fireEvent.change(await screen.findByRole("combobox", { name: "Exchange" }), { target: { value: "binance" } });

    const form = await screen.findByLabelText("API key");
    expect(form.closest("table")).toBeNull();
    const dashed = screen.getByRole("button", { name: "Cancel" });
    expect(dashed.compareDocumentPosition(form) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
