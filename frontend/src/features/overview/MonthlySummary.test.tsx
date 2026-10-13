import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MonthlySummary } from "@/features/overview/MonthlySummary";
import type { Excluded, MonthReturn } from "@/shared/api/types";
import i18n from "@/shared/i18n";

function month(m: number, value: string, year = 2026): MonthReturn {
  return { year, month: m, return: value };
}

function excluded(open = 0, noCapital = 0): Excluded {
  return {
    open_trade_count: open,
    rehearsal_fill_count: 0,
    no_capital_at_open: noCapital,
    unconverted_fee: 0,
    unresolved_allocation_count: 0,
  };
}

const MONTHS = [
  month(7, "0.0310000000"),
  month(8, "0.0540000000"),
  month(9, "-0.0190000000"),
  month(10, "0.0000000000"),
];

function text(): string {
  return (screen.getByTestId("monthly-summary").textContent ?? "").replace(/\s+/g, " ").trim();
}

afterEach(async () => {
  await act(() => i18n.changeLanguage("en"));
});

describe("MonthlySummary", () => {
  it("counts positive months, names the best and the worst, and the open trades left out", () => {
    render(<MonthlySummary monthly={MONTHS} excluded={excluded(3)} />);
    // A month at exactly 0% is not positive.
    expect(text()).toBe("2 of 4 months positive · best +5.4% · worst -1.9% · 3 open trades not in the curve");
  });

  it("adds the trades without capital at open only when there are some", () => {
    const { rerender } = render(<MonthlySummary monthly={MONTHS} excluded={excluded(0, 2)} />);
    expect(text()).toBe(
      "2 of 4 months positive · best +5.4% · worst -1.9% · 2 trades without capital at open",
    );
    rerender(<MonthlySummary monthly={MONTHS} excluded={excluded(1, 1)} />);
    expect(text()).toContain("1 open trade not in the curve · 1 trade without capital at open");
    rerender(<MonthlySummary monthly={MONTHS} excluded={excluded(0, 0)} />);
    expect(text()).toBe("2 of 4 months positive · best +5.4% · worst -1.9%");
  });

  it("uses the singular for one month", () => {
    render(<MonthlySummary monthly={[month(7, "0.0310000000")]} excluded={excluded()} />);
    expect(text()).toBe("1 of 1 month positive · best +3.1% · worst +3.1%");
  });

  it("compares months across years by value", () => {
    render(
      <MonthlySummary
        monthly={[month(12, "-0.0600000000", 2025), month(1, "0.0200000000"), month(2, "0.0100000000")]}
        excluded={excluded()}
      />,
    );
    expect(text()).toBe("2 of 3 months positive · best +2.0% · worst -6.0%");
  });

  it("says nothing about months when none has closed, and nothing at all when nothing is left out", () => {
    const { rerender } = render(<MonthlySummary monthly={[]} excluded={excluded(2)} />);
    expect(text()).toBe("2 open trades not in the curve");
    rerender(<MonthlySummary monthly={[]} excluded={excluded()} />);
    expect(screen.queryByTestId("monthly-summary")).not.toBeInTheDocument();
  });

  it("reads in the active language", async () => {
    await act(() => i18n.changeLanguage("es"));
    render(<MonthlySummary monthly={MONTHS} excluded={excluded(1, 2)} />);
    expect(text()).toBe(
      "2 de 4 meses positivos · mejor +5,4 % · peor -1,9 % · 1 operación abierta fuera de la curva · 2 operaciones sin capital al abrir",
    );
  });

  describe("the Overview's count of open positions, by the optional `open` prop (T13 and T20)", () => {
    const LEAD = "2 of 4 months positive · best +5.4% · worst -1.9%";

    it("writes today's live-only part when `open` is absent (T20: the detail page's second caller)", () => {
      render(<MonthlySummary monthly={MONTHS} excluded={excluded(2)} />);
      expect(text()).toBe(`${LEAD} · 2 open trades not in the curve`);
    });

    it("writes no part about open positions, old or new, when `open` is null (loading or failed)", () => {
      render(<MonthlySummary monthly={MONTHS} excluded={excluded(3)} open={null} />);
      expect(text()).toBe(LEAD);
      expect(text()).not.toContain("open");
    });

    it("writes nothing when the total is zero, whatever the curve leaves out", () => {
      render(<MonthlySummary monthly={MONTHS} excluded={excluded(3)} open={{ total: 0, rehearsal: 0 }} />);
      expect(text()).toBe(LEAD);
    });

    it("writes 'N open' when none of them is dry run, and never today's sentence", () => {
      render(<MonthlySummary monthly={MONTHS} excluded={excluded(5)} open={{ total: 3, rehearsal: 0 }} />);
      expect(text()).toBe(`${LEAD} · 3 open`);
      expect(text()).not.toContain("not in the curve");
    });

    it("writes 'N open, M of them dry run' when some are", () => {
      render(<MonthlySummary monthly={MONTHS} excluded={excluded()} open={{ total: 2, rehearsal: 1 }} />);
      expect(text()).toBe(`${LEAD} · 2 open, 1 of them dry run`);
    });

    it("writes '1 open, dry run' for exactly one position that is dry run", () => {
      render(<MonthlySummary monthly={MONTHS} excluded={excluded()} open={{ total: 1, rehearsal: 1 }} />);
      expect(text()).toBe(`${LEAD} · 1 open, dry run`);
    });

    it("writes 'N open, M of them dry run' when all of several are dry run", () => {
      render(<MonthlySummary monthly={MONTHS} excluded={excluded()} open={{ total: 3, rehearsal: 3 }} />);
      expect(text()).toBe(`${LEAD} · 3 open, 3 of them dry run`);
    });

    it("counts a dry-run position although the curve leaves it out: the count does not read `excluded`", () => {
      render(<MonthlySummary monthly={MONTHS} excluded={excluded(0)} open={{ total: 1, rehearsal: 1 }} />);
      expect(text()).toContain("1 open, dry run");
    });

    it("sits after the worst month and before the trades without capital", () => {
      render(<MonthlySummary monthly={MONTHS} excluded={excluded(0, 2)} open={{ total: 2, rehearsal: 0 }} />);
      expect(text()).toBe(`${LEAD} · 2 open · 2 trades without capital at open`);
    });

    it("stands alone when no month has closed", () => {
      render(<MonthlySummary monthly={[]} excluded={excluded()} open={{ total: 2, rehearsal: 1 }} />);
      expect(text()).toBe("2 open, 1 of them dry run");
    });

    it("draws no line at all when there is nothing to say", () => {
      render(<MonthlySummary monthly={[]} excluded={excluded(4)} open={{ total: 0, rehearsal: 0 }} />);
      expect(screen.queryByTestId("monthly-summary")).not.toBeInTheDocument();
    });

    it.each([
      ["a single position", { total: 1, rehearsal: 0 }, "1 abierta"],
      ["several positions", { total: 3, rehearsal: 0 }, "3 abiertas"],
      ["some dry run", { total: 2, rehearsal: 1 }, "2 abiertas, 1 de ellas en simulación"],
      ["one that is dry run", { total: 1, rehearsal: 1 }, "1 abierta, en simulación"],
      ["several, all dry run", { total: 3, rehearsal: 3 }, "3 abiertas, 3 de ellas en simulación"],
    ])("reads in Spanish for %s", async (_label, open, expected) => {
      await act(() => i18n.changeLanguage("es"));
      render(<MonthlySummary monthly={MONTHS} excluded={excluded()} open={open} />);
      expect(text()).toBe(`2 de 4 meses positivos · mejor +5,4 % · peor -1,9 % · ${expected}`);
    });

    it("keeps today's sentence in Spanish for the second caller", async () => {
      await act(() => i18n.changeLanguage("es"));
      render(<MonthlySummary monthly={MONTHS} excluded={excluded(1)} />);
      expect(text()).toContain("1 operación abierta fuera de la curva");
    });
  });

  it("shows an alert rather than NaN when a month cannot be read", () => {
    const { container } = render(<MonthlySummary monthly={[month(1, "x")]} excluded={excluded()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("The monthly returns could not be read.");
    expect(container).not.toHaveTextContent("NaN");
  });
});
