import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EnableToggle } from "@/features/strategies/EnableToggle";
import type { Strategy } from "@/shared/api/types";
import i18n from "@/shared/i18n";

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    name: "ETH Breakout",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    allocation_percent: "100",
    enabled: false,
    archived_at: null,
    allowed_pairs: ["ETHUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    ...overrides,
  };
}

function renderToggle(subject: Strategy) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <EnableToggle strategy={subject} />
    </QueryClientProvider>,
  );
}

describe("EnableToggle icons (decision 67 Q8)", () => {
  it.each([
    [false, "strategies.detail.enable", "lucide-power"],
    [true, "strategies.detail.disable", "lucide-power-off"],
  ])("with enabled=%s draws an aria-hidden %s icon left of the text, the name unchanged", (enabled, key, icon) => {
    renderToggle(strategy({ enabled }));

    const button = screen.getByRole("button", { name: i18n.t(key) });
    const svg = button.querySelector("svg");
    expect(svg).toHaveClass(icon, "size-4", "shrink-0");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(button.firstElementChild).toBe(svg);
    // Its column stretches it to full width: the icon and text stay centred, as the text alone was.
    expect(button).toHaveClass("inline-flex", "items-center", "justify-center", "gap-1.5");
    expect(button).toHaveAccessibleName(i18n.t(key));
  });
});
