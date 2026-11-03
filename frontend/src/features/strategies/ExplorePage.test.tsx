import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import { jsonResponse, publicStrategy, renderAt, resetExchangeScope, setViewport, stubApi, unlock } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";

function serve(answer: () => Promise<Response>, me: Record<string, unknown> = {}) {
  return stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) => {
    if (url.endsWith("/api/public/strategies")) return answer();
    if (url.endsWith("/api/me")) {
      return Promise.resolve(
        jsonResponse({ email: "a@example.com", is_admin: true, mode: "LIVE", dry_run_brake: false, ...me }),
      );
    }
    return undefined;
  });
}

function open() {
  renderAt(<AppRoutes />, "/strategies/explore");
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
  setViewport("wide");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Explore", () => {
  it("shows a strategy with its author, market and figures, for a user with no pool at all", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ id: ID })])));
    open();

    const row = await screen.findByTestId("public-strategy-row");
    expect(within(row).getByRole("link", { name: "Alpha" })).toHaveAttribute("href", `/strategies/explore/${ID}`);
    expect(within(row).getByText(i18n.t("strategies.public.by", { name: "Ana" }), { exact: false })).toBeInTheDocument();
    expect(within(row).getByTestId("public-market")).toHaveTextContent("bybit · usdt-m · USDT");
    expect(within(row).getByTestId("public-trades")).toHaveTextContent("3");
    expect(within(row).getByTestId("public-return")).toHaveTextContent("+12.5%");
    expect(within(row).getByTestId("public-live")).toHaveTextContent("2");
    expect(within(row).getByTestId("public-capital")).toHaveTextContent("1,500.00 USDT");
  });

  it("names what the return leaves out, beside the figure", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy()])));
    open();

    const row = await screen.findByTestId("public-strategy-row");
    expect(within(row).getByText(i18n.t("strategies.public.return"))).toBeInTheDocument();
  });

  it("colours a loss as a loss", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ unleveraged_return_before_fees: "-0.04" })])));
    open();

    expect(await screen.findByTestId("public-return")).toHaveClass("text-loss");
  });

  it("writes an age in days from the strategy's creation", async () => {
    const tenDaysAgo = new Date(Date.now() - 10 * 86_400_000 - 3_600_000).toISOString();
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ created_at: tenDaysAgo })])));
    open();

    expect(await screen.findByTestId("public-age")).toHaveTextContent(i18n.t("strategies.public.ageDays", { count: 10 }));
  });

  it("claims no return before a real trade has closed, and says so in words", async () => {
    serve(() =>
      Promise.resolve(jsonResponse([publicStrategy({ closed_trade_count: 0, unleveraged_return_before_fees: "0" })])),
    );
    open();

    expect(await screen.findByTestId("public-trades")).toHaveTextContent("0");
    const figure = screen.getByTestId("public-return");
    expect(figure).toHaveTextContent(i18n.t("strategies.public.noRealTrade"));
    expect(figure).not.toHaveTextContent("0");
    expect(figure).not.toHaveClass("text-gain");
    expect(figure).not.toHaveClass("text-loss");
  });

  it("under the brake shows no capital and says why", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ live_subscribers: 0, capital: null })])), {
      dry_run_brake: true,
    });
    open();

    expect(await screen.findByTestId("public-capital")).toHaveTextContent("—");
    expect(await screen.findByText(i18n.t("strategies.explore.brake"))).toBeInTheDocument();
  });

  it("says nothing of the brake when it is off", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy()])));
    open();

    await screen.findByTestId("public-strategy-row");
    expect(screen.queryByText(i18n.t("strategies.explore.brake"))).not.toBeInTheDocument();
  });

  it("writes a capital of zero as zero, not as an absence", async () => {
    serve(() => Promise.resolve(jsonResponse([publicStrategy({ live_subscribers: 0, capital: "0" })])));
    open();

    expect(await screen.findByTestId("public-capital")).toHaveTextContent("0.00 USDT");
  });

  it("says so when nothing is public", async () => {
    serve(() => Promise.resolve(jsonResponse([])));
    open();

    expect(await screen.findByText(i18n.t("strategies.explore.empty"))).toBeInTheDocument();
  });

  it("reads a failed list as an error, never as an empty one", async () => {
    serve(() => Promise.resolve(jsonResponse({ detail: "down" }, 500)));
    open();

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.explore.error"));
    expect(screen.queryByText(i18n.t("strategies.explore.empty"))).not.toBeInTheDocument();
  });

  it("says it is loading while the list is on its way", async () => {
    serve(() => new Promise<Response>(() => undefined));
    open();

    expect(await screen.findByText(i18n.t("strategies.explore.loading"))).toBeInTheDocument();
  });
});
