import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import {
  jsonResponse,
  lock,
  renderAt,
  resetExchangeScope,
  setViewport,
  SIGNED_UP,
  stubApi,
  unlock,
} from "@/test/harness";

/** A signed-in user who is NOT the admin: the section is theirs, not the admin's. */
function serveAsMember() {
  stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) => {
    if (url.endsWith("/api/me")) {
      return Promise.resolve(
        jsonResponse({ email: "member@example.com", is_admin: false, mode: "LIVE", dry_run_brake: false, ...SIGNED_UP }),
      );
    }
    if (url.endsWith("/api/safety-events")) return Promise.resolve(jsonResponse({ events: [] }));
    return undefined;
  });
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
  setViewport("wide");
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

describe("the Safety events section", () => {
  it("is routed at /safety-events for a user who is not the admin", async () => {
    serveAsMember();
    renderAt(<AppRoutes />, "/safety-events");
    expect(await screen.findByRole("heading", { level: 1, name: "Safety events" })).toBeInTheDocument();
  });

  it("is offered in both navigations to a user who is not the admin, beside the admin-only ones hidden", async () => {
    serveAsMember();
    renderAt(<AppRoutes />, "/");
    const navs = await screen.findAllByRole("navigation", { name: "Sections" });
    expect(navs.length).toBeGreaterThan(0);
    for (const nav of navs) {
      expect(within(nav).getByRole("link", { name: "Safety events" })).toHaveAttribute("href", "/safety-events");
      expect(within(nav).queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
    }
  });
});
