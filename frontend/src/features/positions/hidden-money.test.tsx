import { act, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PositionsTable } from "@/features/positions/PositionsTable";
import { useHiddenStore } from "@/shared/hidden/hidden-store";
import i18n from "@/shared/i18n";
import { lock, openPosition, renderAt, setViewport, unlock } from "@/test/harness";

/** S1, L15: an open position's size, fees and margin are the user's own money; its prices and leverage are not. */

beforeEach(async () => {
  unlock();
  setViewport("wide");
  window.localStorage.clear();
  useHiddenStore.setState({ hidden: true });
  await act(() => i18n.changeLanguage("en"));
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  useHiddenStore.setState({ hidden: false });
  await act(() => i18n.changeLanguage("en"));
});

function mount() {
  const position = openPosition({
    markets: ["DOGEUSDT"],
    base_currency: "DOGE",
    side: "LONG",
    size: "76",
    opened_size: "76",
    entry_price: "0.1234",
    fees: "0.55",
    margin_granted: "12.50",
    leverage: "3",
  });
  return renderAt(<PositionsTable positions={[position]} asOf="2026-11-16T10:00:00Z" currency="USDT" labelledBy="h" variant="strategy" />);
}

describe("the open positions table while the balances are hidden", () => {
  it("masks the margin, and keeps the entry price and the leverage; the size and the fees are not in the table (L37)", () => {
    mount();

    const row = within(screen.getAllByRole("rowgroup")[1] as HTMLElement).getAllByRole("row")[0] as HTMLElement;
    const text = row.textContent ?? "";
    expect(within(row).getAllByText("******")).toHaveLength(1);
    expect(text).not.toContain("76");
    expect(text).not.toContain("0.55");
    expect(text).not.toContain("12.50");
    expect(text).toContain("0.1234");
    expect(text).toContain("3x");
  });

  it("writes every figure while they are shown", () => {
    useHiddenStore.setState({ hidden: false });
    mount();

    const row = within(screen.getAllByRole("rowgroup")[1] as HTMLElement).getAllByRole("row")[0] as HTMLElement;
    expect(within(row).queryByText("******")).not.toBeInTheDocument();
    expect(row.textContent).toContain("0.1234");
    expect(row.textContent).toContain("12.50");
    expect(row.textContent).toContain("3x");
  });
});
