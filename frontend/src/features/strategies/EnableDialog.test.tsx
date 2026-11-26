import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EnableToggle } from "@/features/strategies/EnableToggle";
import type { Strategy } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import { jsonResponse } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const NAME = "ETH Breakout";
const REF_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: ID,
    name: NAME,
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    subscription: null,
    enabled: true,
    archived_at: null,
    allowed_pairs: ["ETHUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    visibility: "PRIVATE",
    share_token: null,
    secret_last4: "x4F2",
    description: null,
    subscribers: 1,
    live_subscribers: 0,
    created_at: null,
    capital: null,
    stop_loss_pct: "10.00",
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

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function disableAndConfirm() {
  fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.detail.disable") }));
  fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.enableDialog.disable") }));
}

afterEach(async () => {
  vi.unstubAllGlobals();
  await i18n.changeLanguage("en");
});

// Opened from the actions cell of My strategies, whose nowrap and end alignment a dialog inherits from its DOM
// ancestor: the question ran off its own box (L35).
describe("EnableDialog inside a table cell", () => {
  it("is wide enough for its text and wraps it, starting each line at the beginning, whatever the cell around it sets", () => {
    renderToggle(strategy());

    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.detail.disable") }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveClass("w-[calc(100%-2rem)]", "max-w-lg", "whitespace-normal", "break-words", "text-left");
  });
});

describe("EnableDialog, a disable refused for exposure", () => {
  it("says the strategy still has an open position and names what holds it, as archive does", async () => {
    stubFetch(
      jsonResponse(
        {
          detail: {
            error: "OPEN_POSITION",
            message: "server text",
            symbols: ["ETHUSDT", "SOLUSDT"],
            allocations: [REF_A],
            live_reservations: [],
            in_flight_attempts: [],
          },
        },
        409,
      ),
    );
    renderToggle(strategy());

    disableAndConfirm();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(i18n.t("strategies.enableDialog.openPosition"));
    expect(alert).not.toHaveTextContent(i18n.t("strategies.row.toggleError"));
    expect(within(alert).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Open position on: ETHUSDT, SOLUSDT",
      "1 open allocation",
    ]);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("shows the main sentence alone when the refusal names nothing it can trust", async () => {
    stubFetch(jsonResponse({ detail: { error: "OPEN_POSITION", message: "m" } }, 409));
    renderToggle(strategy());

    disableAndConfirm();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(i18n.t("strategies.enableDialog.openPosition"));
    expect(within(alert).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("keeps the generic message for any other failure", async () => {
    stubFetch(jsonResponse({ detail: { error: "SUBSCRIBERS_CHANGED", message: "m" } }, 409));
    renderToggle(strategy());

    disableAndConfirm();

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.row.toggleError"));
  });

  it("closes the question when the disable is accepted", async () => {
    const fetchMock = stubFetch(jsonResponse(strategy({ enabled: false })));
    renderToggle(strategy());

    disableAndConfirm();

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
