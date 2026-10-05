import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TradeDetailDialog } from "@/features/strategies/TradeDetailDialog";
import type { OperationFill, StrategyTrade } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { jsonResponse, lock, renderAt, unlock } from "@/test/harness";

// The detail dialog (decision 43, design § F): presentational, every figure from the row it was
// opened from, with no request for them; only its fills table asks the server, by being mounted.

const STRATEGY = "11111111-1111-4111-8111-111111111111";
const ALLOCATION = "0b6f0000-0000-4000-8000-000000000001";

function trade(overrides: Partial<StrategyTrade> = {}): StrategyTrade {
  return {
    allocation_id: ALLOCATION,
    pair: "STXUSDT",
    direction: "LONG",
    opened_at: "2026-09-30T10:00:00Z",
    closed_at: "2026-09-30T12:30:00.000001Z",
    rehearsal: false,
    rehearsal_fill_price: null,
    base_currency: "STX",
    entry_price: "0.451200000000000000",
    exit_price: "0.463100000000000000",
    size: "1250.000000000000000000",
    fees: "0.630000000000000000",
    other_fees: [],
    pnl: "14.25",
    capital_at_open: "1000.000000000000000000",
    return: "0.0142450000",
    fees_complete: true,
    ...overrides,
  };
}

const fill = (overrides: Partial<OperationFill> = {}): OperationFill => ({
  filled_at: "2026-09-30T10:00:00Z",
  side: "BUY",
  price: "0.451200000000000000",
  quantity: "1250.000000000000000000",
  fee: "0.310000000000000000",
  fee_currency: "USDT",
  rehearsal: false,
  ...overrides,
});

/** Stubs fetch; every URL asked is recorded, and the fills route answers `fills` (never, if null). */
function serve(fills: unknown | null = { allocation_id: ALLOCATION, fills: [fill()], truncated: false }) {
  const requests: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      requests.push(String(input));
      return fills === null ? new Promise<Response>(() => undefined) : Promise.resolve(jsonResponse(fills));
    }),
  );
  return requests;
}

function renderDialog(row: StrategyTrade, locale = "en", onClose: () => void = () => undefined) {
  renderAt(<TradeDetailDialog strategyId={STRATEGY} trade={row} currency="USDT" locale={locale} onClose={onClose} />);
}

const text = (path: string) => i18n.t(`strategies.performance.trades.${path}`);
const shows = (find: () => HTMLElement | null) => vi.waitFor(() => expect(find()).toBeInTheDocument());

/** The `dd` that follows the `dt` with this label, or null. */
function figure(label: string): HTMLElement | null {
  const term = screen.queryByText(label, { selector: "dt" });
  return (term?.nextElementSibling as HTMLElement | null) ?? null;
}

beforeEach(unlock);
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

describe("TradeDetailDialog", () => {
  it("shows the pair and the side in the title and every figure of the row", async () => {
    serve(null);
    renderDialog(trade());

    expect(screen.queryByText("STXUSDT · LONG")).toBeInTheDocument();
    expect(figure("Opened (UTC)")?.textContent).toBe("Sep 30, 2026, 10:00");
    expect(figure("Closed (UTC)")?.textContent).toBe("Sep 30, 2026, 12:30");
    expect(figure("Entry price")?.textContent).toBe("0.4512");
    expect(figure("Exit price")?.textContent).toBe("0.4631");
    expect(figure("Size (STX)")?.textContent).toBe("1250");
    expect(figure("Fees paid (USDT)")?.textContent).toBe("0.63");
    expect(figure("PnL (USDT)")?.textContent).toBe("+14.25");
    expect(figure("PnL %")?.textContent ?? "").toContain("+1.4%");
    expect(screen.queryByText("PnL over the pool's capital when the operation opened, not over the position's margin.")).toBeInTheDocument();
    expect(figure("Pool capital at open (USDT)")?.textContent).toBe("1,000.00");
    expect(figure("Operation id")?.textContent).toBe(ALLOCATION);
  });

  it("shows fees in other currencies only when there are some", async () => {
    serve(null);
    renderDialog(trade({ other_fees: [{ currency: "BNB", amount: "0.000120000000000000" }] }));

    expect(figure("Fees in other currencies")?.textContent ?? "").toContain("+ 0.00012 BNB");
  });

  it("shows no fees-in-other-currencies line when there are none", async () => {
    serve(null);
    renderDialog(trade());

    // Anchored on a line the dialog does draw, so a blank dialog cannot pass this.
    expect(screen.queryByText("Fees paid (USDT)")).toBeInTheDocument();
    expect(screen.queryByText("Fees in other currencies")).toBeNull();
  });

  it("shows the table's em dash for a null figure", async () => {
    serve(null);
    renderDialog(trade({ capital_at_open: null, return: null }));

    expect(figure("Pool capital at open (USDT)")?.textContent ?? "").toContain("—");
    expect(figure("PnL %")?.textContent ?? "").toContain("—");
  });

  it("renders its figures with the fills request still pending, and no request was made for the figures", async () => {
    const requests = serve(null);
    renderDialog(trade());

    expect(screen.queryByText("Loading the fills…")).toBeInTheDocument();
    expect(figure("Entry price")?.textContent).toBe("0.4512");
    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatch(new RegExp(`/performance/strategies/${STRATEGY}/trades/${ALLOCATION}/fills$`));
  });

  it.each([
    ["FIXED_ONE", "Dry run · fixed price", "Dry run at a fixed price: it was opened at a fixed price of 1, whatever the market price was. Its prices and its PnL are not a result. It is not counted in any total."],
    ["ALERT", "Dry run · alert price", "Dry run at the alert's price: opened by the simulated exchange at the price its alert carried, not at the venue. It was sized at 1x and its fee is simulated at the taker rate, so its PnL is not what it would have made live. It is not counted in any total."],
    ["UNDETERMINED", "Dry run", "Dry run: filled by the simulated exchange, not at the venue. It is not counted in any total."],
  ])("carries the tag in the title and the sentence of its kind for a %s operation", async (kind, tag, sentence) => {
    serve(null);
    renderDialog(trade({ rehearsal: true, rehearsal_fill_price: kind }));

    expect(screen.queryByText("STXUSDT · LONG")?.parentElement?.textContent ?? "").toContain(tag);
    expect(screen.queryByText(sentence)).toBeInTheDocument();
  });

  it("writes the ALERT sentence in Spanish, exactly", async () => {
    await i18n.changeLanguage("es");
    serve(null);
    renderDialog(trade({ rehearsal: true, rehearsal_fill_price: "ALERT" }), "es");

    expect(
      screen.queryByText(
        "Simulación al precio de la alerta: abierta por el exchange simulado al precio que traía su alerta, no en el exchange real. Se dimensionó a 1x y su comisión es simulada a la tasa taker, así que su PnL no es el que habría dado en real. No se cuenta en ningún total.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the general dry-run sentence for a value the panel does not know", async () => {
    serve(null);
    renderDialog(trade({ rehearsal: true, rehearsal_fill_price: "SLIPPED" }));

    expect(screen.queryByText("Dry run: filled by the simulated exchange, not at the venue. It is not counted in any total.")).toBeInTheDocument();
  });

  it("shows no rehearsal sentence for a real operation", async () => {
    serve(null);
    renderDialog(trade());

    // Anchored on the title, so a blank dialog cannot pass this.
    expect(screen.queryByText("STXUSDT · LONG")).toBeInTheDocument();
    expect(screen.queryByText(/Dry run/)).toBeNull();
    expect(screen.queryByText(/not counted in any total/)).toBeNull();
  });

  it("calls onClose from the Close button and from Escape", async () => {
    serve(null);
    const onClose = vi.fn();
    renderDialog(trade(), "en", onClose);

    const close = screen.queryByRole("button", { name: "Close" });
    expect(close).toBeInTheDocument();
    fireEvent.click(close as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(1);

    const dialog = document.querySelector("dialog") as HTMLDialogElement;
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
    fireEvent(dialog, new Event("cancel", { cancelable: true }));
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("is modal: showModal is called and focus moves into it", async () => {
    serve(null);
    // jsdom may not implement showModal: define it on the prototype of a real dialog element, then restore.
    const proto = Object.getPrototypeOf(document.createElement("dialog")) as { showModal?: () => void };
    const original = Object.getOwnPropertyDescriptor(proto, "showModal");
    const showModal = vi.fn(function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
    });
    Object.defineProperty(proto, "showModal", { value: showModal, configurable: true, writable: true });
    try {
      renderDialog(trade());

      expect(showModal).toHaveBeenCalledTimes(1);
      const dialog = document.querySelector("dialog") as HTMLDialogElement;
      expect(dialog.contains(document.activeElement)).toBe(true);
      expect(document.activeElement).not.toBe(document.body);
    } finally {
      if (original === undefined) delete proto.showModal;
      else Object.defineProperty(proto, "showModal", original);
    }
  });

  it("opens an operation with no base currency: Size with an em dash and its reason, and Quantity in the fills table", async () => {
    serve();
    renderDialog(trade({ base_currency: null, entry_price: null, exit_price: null, size: null }));

    const size = figure("Size");
    expect(size).toBeInTheDocument();
    expect(size?.textContent ?? "").toContain("—");
    expect(within(size as HTMLElement).queryByText(text("notDerivable"))).toBeInTheDocument();
    expect(screen.queryByText(/Size \(/)).toBeNull();
    await shows(() => screen.queryByRole("table", { name: "Fills" }));
    expect(screen.getAllByRole("columnheader").map((header) => header.textContent)).toContain("Quantity");
  });

  it("has every key it uses in English and in Spanish", () => {
    const keys = [
      "detail.title",
      "detail.entryPrice",
      "detail.exitPrice",
      "detail.size",
      "detail.sizeNoBase",
      "detail.fees",
      "detail.otherFees",
      "detail.pnl",
      "detail.pnlPercent",
      "detail.returnHint",
      "detail.capital",
      "detail.rehearsalHint",
      "detail.rehearsalFixedHint",
      "detail.rehearsalAlertHint",
      "detail.operationId",
      "detail.close",
      "rehearsal",
      "rehearsalFixed",
      "rehearsalAlert",
    ];
    const read = (locale: typeof en, path: string): unknown =>
      path.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], locale.strategies.performance.trades);
    for (const locale of [en, es]) {
      expect(keys.filter((key) => typeof read(locale, key) !== "string")).toEqual([]);
    }
  });
});
