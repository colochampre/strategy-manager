import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import { jsonResponse, renderAt, resetExchangeScope, setViewport, SIGNED_UP, stubApi, unlock } from "@/test/harness";

function serve(suspended: boolean) {
  stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) =>
    url.endsWith("/api/me")
      ? Promise.resolve(
          jsonResponse({ email: "ana@example.com", is_admin: false, mode: "LIVE", dry_run_brake: false, ...SIGNED_UP, suspended }),
        )
      : undefined,
  );
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
  setViewport("wide");
});

afterEach(async () => {
  vi.unstubAllGlobals();
  await i18n.changeLanguage("en");
});

describe("a suspended account in the shell (public-site LS9)", () => {
  it("shows the notice and none of the navigation", async () => {
    serve(true);
    renderAt(<AppRoutes />, "/");

    expect(await screen.findByRole("heading", { name: "Your account is suspended" })).toBeInTheDocument();
    expect(screen.queryAllByRole("navigation", { name: "Sections" })).toHaveLength(0);
    expect(screen.queryAllByRole("navigation", { name: "Exchanges" })).toHaveLength(0);
  });

  it("still opens the way out", async () => {
    serve(true);
    renderAt(<AppRoutes />, "/way-out");

    expect(await screen.findByRole("heading", { level: 1, name: i18n.t("wayOut.title") })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Your account is suspended" })).toBeNull();
  });

  it("shows an account that is not suspended its navigation", async () => {
    serve(false);
    renderAt(<AppRoutes />, "/");

    await screen.findAllByRole("navigation", { name: "Sections" });
    expect(screen.queryByRole("heading", { name: "Your account is suspended" })).toBeNull();
  });
});
