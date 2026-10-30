import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StrategyHeader } from "@/features/strategies/StrategyHeader";
import type { Strategy } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import { jsonResponse, lock, unlock } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const SECRET = "s3cr3t-Vh4lu3-Zq9";
const PLACEHOLDER_URL = "/webhook/tradingview?secret=<your secret>";

const STRATEGY: Strategy = {
  id: ID,
  name: "ETH Breakout",
  exchange: "bybit",
  venue: "usdt-m",
  settlement_currency: "USDT",
  fill_mode: "SKIP",
  subscription: null,
  enabled: false,
  archived_at: null,
  allowed_pairs: ["ETHUSDT"],
  uptime: { seconds: 0, first_enabled_at: null, baseline: false },
  visibility: "PRIVATE",
};

function setup(strategy: Strategy = STRATEGY) {
  const secretCalls: string[] = [];
  vi.stubGlobal("fetch", (input: RequestInfo | URL) => {
    // The block also reads the webhook's host when it opens; it is not a call for the secret.
    if (String(input).endsWith("/webhook-origin")) return Promise.resolve(jsonResponse({ origin: null }));
    secretCalls.push(String(input));
    return Promise.resolve(jsonResponse({ webhook_secret: SECRET }));
  });
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <StrategyHeader strategy={strategy} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { queryClient, secretCalls };
}

const toggle = () => screen.getByRole("button", { name: "Connect a TradingView alert" });
const webhookHeading = () => screen.queryByRole("heading", { name: "Connect a TradingView alert" });

beforeEach(unlock);
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

describe("StrategyHeader webhook disclosure", () => {
  it("draws an aria-hidden Webhook left of the toggle's text and leaves its name as it was", () => {
    setup();

    const svg = toggle().querySelector("svg");
    expect(svg).toHaveClass("lucide-webhook", "size-4", "shrink-0");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(toggle().firstElementChild).toBe(svg);
    expect(toggle()).toHaveClass("inline-flex", "items-center", "gap-1.5");
    expect(toggle()).toHaveAccessibleName("Connect a TradingView alert");
  });

  it("test_the_webhook_block_is_closed_by_default_and_opened_by_a_button_in_the_header", () => {
    setup();

    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(webhookHeading()).toBeNull();
    expect(screen.queryByRole("group", { name: "Alert message" })).toBeNull();
    expect(document.body.textContent).not.toContain(PLACEHOLDER_URL);

    fireEvent.click(toggle());

    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    expect(webhookHeading()).toBeInTheDocument();
    expect(screen.getByText(PLACEHOLDER_URL)).toBeInTheDocument();
    expect(JSON.parse(screen.getByRole("group", { name: "Alert message" }).textContent ?? "")).toMatchObject({
      signal_type: ID,
    });
  });

  it("points aria-controls at the panel that holds the block, closed or open", () => {
    setup();
    const controlled = () => document.getElementById(toggle().getAttribute("aria-controls") ?? "");

    expect(controlled()).not.toBeNull();
    expect(controlled()).toBeEmptyDOMElement();

    fireEvent.click(toggle());

    expect(controlled()).toContainElement(webhookHeading());
  });

  it("opens in the page flow under the header's title, not as a floating popover", () => {
    setup();

    fireEvent.click(toggle());

    const panel = document.getElementById(toggle().getAttribute("aria-controls") ?? "") as HTMLElement;
    const title = screen.getByRole("heading", { level: 1, name: "ETH Breakout" });
    expect(title.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    for (let node: HTMLElement | null = panel; node !== null && node.tagName !== "BODY"; node = node.parentElement) {
      expect(node.className).not.toMatch(/\b(absolute|fixed|sticky|z-\d+)\b/);
    }
  });

  it("closes again on a second click and unmounts the block", () => {
    setup();
    fireEvent.click(toggle());

    fireEvent.click(toggle());

    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(webhookHeading()).toBeNull();
    expect(screen.queryByRole("group", { name: "Alert message" })).toBeNull();
  });

  it("test_collapsing_after_a_regeneration_leaves_nothing_in_the_cache_and_reopening_shows_the_placeholder_without_a_request", async () => {
    const { queryClient, secretCalls } = setup();
    fireEvent.click(toggle());
    fireEvent.click(screen.getByRole("button", { name: "Regenerate secret" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Regenerate" }));
    expect(await screen.findByText(`/webhook/tradingview?secret=${SECRET}`)).toBeInTheDocument();
    expect(secretCalls).toHaveLength(1);
    expect(queryClient.getMutationCache().getAll()).toHaveLength(1);

    fireEvent.click(toggle());

    await waitFor(() => expect(queryClient.getMutationCache().getAll()).toHaveLength(0));
    expect(document.body.textContent).not.toContain(SECRET);

    fireEvent.click(toggle());

    expect(screen.getByText(PLACEHOLDER_URL)).toBeInTheDocument();
    expect(secretCalls).toHaveLength(1);
    expect(document.body.textContent).not.toContain(SECRET);
  });

  it("offers no regeneration of an archived strategy's secret", () => {
    setup({ ...STRATEGY, archived_at: "2026-10-01T00:00:00Z" });
    fireEvent.click(toggle());

    expect(screen.getByRole("button", { name: "Regenerate secret" })).toBeDisabled();
  });

  it("is labelled in Spanish", async () => {
    await i18n.changeLanguage("es");
    setup();

    const button = screen.getByRole("button", { name: "Conectar una alerta de TradingView" });
    expect(button).toHaveAttribute("aria-expanded", "false");
  });
});
