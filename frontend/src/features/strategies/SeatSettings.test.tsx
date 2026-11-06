import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SeatSettings } from "@/features/strategies/SeatSettings";
import type { Strategy } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import { jsonResponse, subscriptionOf } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const SUBSCRIPTION_ID = "33333333-3333-4333-8333-333333333333";

function strategy(leverage: number): Pick<Strategy, "id" | "subscription" | "archived_at"> {
  return {
    id: ID,
    archived_at: null,
    subscription: subscriptionOf(ID, "30", { id: SUBSCRIPTION_ID, leverage }),
  };
}

/** A pool of 1000 USDT: the margin of a share is 10 x share, the notional that times the leverage asked. */
function previewAt(path: string) {
  const params = new URL(path, "http://panel.test").searchParams;
  const share = params.get("share") ?? "30";
  const leverage = params.get("leverage");
  const amount = Number(share) * 10;
  return jsonResponse({
    strategy_id: ID,
    pool: { exchange: "bybit", venue: "usdt-m", settlement_currency: "USDT" },
    currency: "USDT",
    pool_minimum: "5.000000000000000000",
    balance: { total: "1000.000000000000000000", observed_at: "2026-10-09T14:03:12Z", stale: false },
    exact: {
      share,
      amount: amount.toFixed(18),
      below_pool_minimum: false,
      notional: leverage === null ? null : (amount * Number(leverage)).toFixed(18),
    },
    steps: Array.from({ length: 100 }, (_unused, index) => ({
      share: index + 1,
      amount: (10 * (index + 1)).toFixed(18),
      below_pool_minimum: false,
    })),
  });
}

function setup(leverage: number) {
  const leverages: Array<string | null> = [];
  const patches: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.startsWith(`/api/strategies/${ID}/share-preview`)) {
        leverages.push(new URL(path, "http://panel.test").searchParams.get("leverage"));
        return Promise.resolve(previewAt(path));
      }
      if (init?.method === "PATCH" && path === `/api/subscriptions/${SUBSCRIPTION_ID}`) {
        patches.push(String(init.body));
        return Promise.resolve(jsonResponse(subscriptionOf(ID, "30", { id: SUBSCRIPTION_ID, leverage })));
      }
      return Promise.resolve(jsonResponse({ detail: "not served by this test" }, 404));
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SeatSettings strategy={strategy(leverage)} />
    </QueryClientProvider>,
  );
  return { leverages, patches };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const leverageField = () => screen.getByRole("textbox", { name: i18n.t("strategies.leverage.label") });
const shareField = () => screen.getByRole("textbox", { name: i18n.t("strategies.detail.share.label") });
const shareRegion = () => screen.getByRole("region", { name: i18n.t("strategies.detail.share.label") });
const leverageRegion = () => screen.getByRole("region", { name: i18n.t("strategies.leverage.label") });
const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 30));

describe("SeatSettings, one leverage draft for the notional and the leverage editor", () => {
  it("the notional follows a leverage being moved, before Save", async () => {
    const { leverages, patches } = setup(3);
    expect(await screen.findByText("Margin: 300.00 USDT · Notional: 900.00 USDT")).toBeInTheDocument();

    fireEvent.change(leverageField(), { target: { value: "5" } });

    expect(await screen.findByText("Margin: 300.00 USDT · Notional: 1,500.00 USDT")).toBeInTheDocument();
    expect(leverages.at(-1)).toBe("5");
    await tick();
    expect(patches).toHaveLength(0);
  });

  it("an invalid leverage draft leaves the notional at the saved leverage", async () => {
    setup(3);
    expect(await screen.findByText("Margin: 300.00 USDT · Notional: 900.00 USDT")).toBeInTheDocument();

    fireEvent.change(leverageField(), { target: { value: "" } });
    await tick();

    expect(screen.getByText("Margin: 300.00 USDT · Notional: 900.00 USDT")).toBeInTheDocument();
  });

  it("each Save sends only its own field", async () => {
    const { patches } = setup(3);
    await screen.findByText("Margin: 300.00 USDT · Notional: 900.00 USDT");

    fireEvent.change(leverageField(), { target: { value: "5" } });
    fireEvent.click(within(leverageRegion()).getByRole("button", { name: i18n.t("strategies.leverage.save") }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toBe('{"leverage":5}');

    fireEvent.change(shareField(), { target: { value: "45" } });
    fireEvent.click(within(shareRegion()).getByRole("button", { name: i18n.t("strategies.detail.share.save") }));
    await waitFor(() => expect(patches).toHaveLength(2));
    expect(patches[1]).toBe('{"allocation_percent":"45"}');
  });
});
