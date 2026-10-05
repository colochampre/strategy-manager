import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OperationFillsTable } from "@/features/strategies/OperationFillsTable";
import type { OperationFill } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import { jsonResponse, lock, renderAt, unlock } from "@/test/harness";

// The fills table of the detail view (decision 43, design § F). It is tested as a component with
// props and a stubbed fetch; the dialog that mounts it is built later, so what only the dialog can
// prove (the table inside its scrolling body) is not asserted here.

const STRATEGY = "11111111-1111-4111-8111-111111111111";
const ALLOCATION = "0b6f0000-0000-4000-8000-000000000001";
const FILLS_PATH = `/performance/strategies/${STRATEGY}/trades/${ALLOCATION}/fills`;

function fill(overrides: Partial<OperationFill> = {}): OperationFill {
  return {
    filled_at: "2026-09-30T12:00:00.123456Z",
    side: "BUY",
    price: "0.451200000000000000",
    quantity: "1250.000000000000000000",
    fee: "0.310000000000000000",
    fee_currency: "USDT",
    rehearsal: false,
    ...overrides,
  };
}

const SELL = () =>
  fill({ side: "SELL", price: "0.463100000000000000", fee: "0.320000000000000000", filled_at: "2026-09-30T14:30:00Z" });

function body(overrides: Record<string, unknown> = {}) {
  return { allocation_id: ALLOCATION, fills: [fill(), SELL()], truncated: false, ...overrides };
}

type Answer = () => Promise<Response>;

/** Stubs fetch: the fills route answers `answer`, and every request to it is recorded. */
function serveFills(answer: Answer) {
  const requests: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (!url.endsWith(FILLS_PATH)) return Promise.reject(new Error(`unexpected fetch: ${url}`));
      requests.push(url);
      return answer();
    }),
  );
  return requests;
}

const answerWith = (answer: unknown, status = 200): Answer => () => Promise.resolve(jsonResponse(answer, status));

function renderFills(operationRehearsal = false, baseCurrency: string | null = "STX") {
  renderAt(
    <OperationFillsTable
      strategyId={STRATEGY}
      allocationId={ALLOCATION}
      baseCurrency={baseCurrency}
      operationRehearsal={operationRehearsal}
    />,
  );
}

const text = (key: string) => i18n.t(`strategies.performance.trades.${key}`);

/** Waits for an element to appear, failing on the assertion and never on a query that throws. */
const shows = (find: () => HTMLElement | null) => vi.waitFor(() => expect(find()).toBeInTheDocument());
const bodyRows = () => {
  const rowgroups = screen.getAllByRole("rowgroup");
  return within(rowgroups[1] as HTMLElement).getAllByRole("row");
};

beforeEach(unlock);
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

describe("OperationFillsTable", () => {
  it("shows the loading line, then one line per fill in order", async () => {
    let release: (response: Response) => void = () => undefined;
    serveFills(() => new Promise<Response>((resolve) => (release = resolve)));
    renderFills();

    expect(screen.queryByText("Loading the fills…")).toBeInTheDocument();

    release(jsonResponse(body()));

    await shows(() => screen.queryByRole("table", { name: "Fills" }));
    expect(screen.queryByText("Loading the fills…")).toBeNull();
    const rows = bodyRows().map((row) => within(row).getAllByRole("cell").map((cell) => cell.textContent));
    expect(rows).toEqual([
      ["Sep 30, 2026, 12:00", "Buy", "0.4512", "1250", "0.31 USDT"],
      ["Sep 30, 2026, 14:30", "Sell", "0.4631", "1250", "0.32 USDT"],
    ]);
    expect(screen.getAllByRole("columnheader").map((header) => header.textContent)).toEqual([
      "Time (UTC)",
      "Side",
      "Price",
      "Quantity (STX)",
      "Fee",
    ]);
  });

  it("says only the first 200 fills are shown when truncated is true, and says nothing otherwise", async () => {
    serveFills(answerWith(body({ truncated: true })));
    renderFills();

    await shows(() => screen.queryByText("Only the first 200 fills are shown."));
  });

  it("says nothing about truncation when truncated is false", async () => {
    serveFills(answerWith(body()));
    renderFills();

    await shows(() => screen.queryByRole("table", { name: "Fills" }));

    expect(screen.queryByText(/Only the first/)).toBeNull();
  });

  it.each([
    ["a 404 no such operation", () => Promise.resolve(jsonResponse({ detail: "no such operation" }, 404))],
    ["a network failure", () => Promise.reject(new TypeError("offline"))],
    ["a missing route", () => Promise.resolve(jsonResponse({ detail: "Not Found" }, 404))],
  ])("shows the error with Try again after %s, and activating it repeats the request", async (_name, answer) => {
    const requests = serveFills(answer);
    renderFills();

    await shows(() => screen.queryByText("The fills could not be loaded."));
    expect(screen.queryByRole("table")).toBeNull();
    expect(requests).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    await vi.waitFor(() => expect(requests).toHaveLength(2));
  });

  it("shows the table once Try again is answered", async () => {
    let healthy = false;
    serveFills(() =>
      Promise.resolve(healthy ? jsonResponse(body()) : jsonResponse({ detail: "no such operation" }, 404)),
    );
    renderFills();
    await shows(() => screen.queryByText("The fills could not be loaded."));

    healthy = true;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    await shows(() => screen.queryByRole("table", { name: "Fills" }));
    expect(screen.queryByText("The fills could not be loaded.")).toBeNull();
  });

  it.each([
    ["another allocation id", body({ allocation_id: "0b6f0000-0000-4000-8000-000000000002" })],
    ["an empty list", body({ fills: [] })],
    ["a side of HOLD", body({ fills: [fill({ side: "HOLD" as OperationFill["side"] })] })],
    ["a price that is a JSON number", body({ fills: [{ ...fill(), price: 0.4512 }] })],
  ])("shows the failed state and draws no line for a malformed body: %s", async (_name, answer) => {
    serveFills(answerWith(answer));
    renderFills();

    await shows(() => screen.queryByText("The fills could not be loaded."));
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryAllByRole("row")).toHaveLength(0);
  });

  it("tags a fill whose rehearsal flag differs from the operation's with Dry run, and no other", async () => {
    serveFills(answerWith(body({ fills: [fill(), fill({ rehearsal: true, side: "SELL" })] })));
    renderFills(false);

    await shows(() => screen.queryByRole("table", { name: "Fills" }));

    const [real, simulated] = bodyRows() as [HTMLElement, HTMLElement];
    expect(within(real).queryByText(text("rehearsal"))).toBeNull();
    expect(within(simulated).queryByText(text("rehearsal"))).toBeInTheDocument();
  });

  it("tags no fill when every flag equals the operation's", async () => {
    serveFills(answerWith(body({ fills: [fill({ rehearsal: true }), fill({ rehearsal: true, side: "SELL" })] })));
    renderFills(true);

    await shows(() => screen.queryByRole("table", { name: "Fills" }));

    expect(screen.queryByText(text("rehearsal"))).toBeNull();
  });

  // Follow-up of the owner answer of 2026-10-05: an operation whose figures cannot be derived has no
  // base currency, and its Quantity heading reads without the parenthesis; no currency is guessed.
  it("reads the Quantity heading without a parenthesis when the base currency is null", async () => {
    serveFills(answerWith(body()));
    renderFills(false, null);

    await shows(() => screen.queryByRole("table", { name: "Fills" }));

    const headings = screen.getAllByRole("columnheader").map((header) => header.textContent);
    expect(headings).toEqual(["Time (UTC)", "Side", "Price", "Quantity", "Fee"]);
  });

  it("reads Cantidad without a parenthesis in Spanish when the base currency is null", async () => {
    await i18n.changeLanguage("es");
    serveFills(answerWith(body()));
    renderFills(false, null);

    await shows(() => screen.queryByRole("table", { name: "Ejecuciones" }));

    expect(screen.getAllByRole("columnheader").map((header) => header.textContent)).toContain("Cantidad");
  });

  it("is a real table with a caption titled Fills", async () => {
    serveFills(answerWith(body()));
    renderFills();

    await shows(() => screen.queryByRole("table", { name: "Fills" }));
    const table = screen.getByRole("table", { name: "Fills" });

    expect(table.querySelector("caption")?.textContent).toBe("Fills");
    expect(table.querySelectorAll("thead th")).toHaveLength(5);
  });

  describe("in Spanish", () => {
    beforeEach(async () => {
      await i18n.changeLanguage("es");
    });

    it("writes the loading line", () => {
      serveFills(() => new Promise<Response>(() => undefined));
      renderFills();

      expect(screen.queryByText("Cargando las ejecuciones…")).toBeInTheDocument();
    });

    it("writes the caption, the sides and the headings", async () => {
      serveFills(answerWith(body()));
      renderFills();

      await shows(() => screen.queryByRole("table", { name: "Ejecuciones" }));
      expect(screen.queryByText("Compra")).toBeInTheDocument();
      expect(screen.queryByText("Venta")).toBeInTheDocument();
      expect(screen.getAllByRole("columnheader").map((header) => header.textContent)).toEqual([
        "Hora (UTC)",
        "Lado",
        "Precio",
        "Cantidad (STX)",
        "Comisión",
      ]);
    });

    it("writes the error and the retry button, and the truncation sentence", async () => {
      serveFills(answerWith({ detail: "no such operation" }, 404));
      renderFills();

      await shows(() => screen.queryByText("No se pudieron cargar las ejecuciones."));
      expect(screen.queryByRole("button", { name: "Reintentar" })).toBeInTheDocument();
    });

    it("writes the truncation sentence", async () => {
      serveFills(answerWith(body({ truncated: true })));
      renderFills();

      await shows(() => screen.queryByText("Solo se muestran las primeras 200 ejecuciones."));
    });
  });
});
