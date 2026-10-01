import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import { lock, renderAt, stubApi, unlock } from "@/test/harness";

const STRATEGY_ID = "5b0c7a52-6f43-4d6e-9c1c-0c2f3f3f2a11";

describe("route map", () => {
  beforeEach(() => {
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
    unlock();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    lock();
  });

  it("test_route_map_renders_overview_strategies_strategy_detail_settings_in_memory_router", async () => {
    const cases: Array<[string, string]> = [
      ["/", "Overview"],
      ["/strategies", "Strategies"],
      [`/strategies/${STRATEGY_ID}`, "Strategy"],
      ["/settings", "Settings"],
    ];
    for (const [path, title] of cases) {
      const { unmount } = renderAt(<AppRoutes />, path);
      expect(await screen.findByRole("heading", { level: 1, name: title })).toBeInTheDocument();
      unmount();
    }
  });

  it("hands the strategy id in the path to the detail page", async () => {
    renderAt(<AppRoutes />, `/strategies/${STRATEGY_ID}`);

    expect(await screen.findByText(STRATEGY_ID)).toBeInTheDocument();
  });

  it("test_unknown_path_renders_not_found_client_side", async () => {
    renderAt(<AppRoutes />, "/no/such/page");

    expect(await screen.findByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to overview" })).toHaveAttribute("href", "/");
  });

  it("keeps the shell around the not-found page", async () => {
    renderAt(<AppRoutes />, "/no/such/page");

    expect(await screen.findAllByRole("navigation", { name: "Sections" })).toHaveLength(2);
  });

  it("keeps pending bookings reachable from the overview, behind the token gate", async () => {
    renderAt(<AppRoutes />, "/");

    expect(await screen.findByText("Nothing needs your decision.")).toBeInTheDocument();
  });

  it("asks for the admin token instead of any page while locked", async () => {
    lock();
    renderAt(<AppRoutes />, "/settings");

    expect(await screen.findByRole("button", { name: "Unlock" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1, name: "Settings" })).not.toBeInTheDocument();
  });
});
