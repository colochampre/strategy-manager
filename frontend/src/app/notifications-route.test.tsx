import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import { jsonResponse, lock, renderAt, resetExchangeScope, setViewport, SIGNED_UP, stubApi, unlock } from "@/test/harness";

/** A signed-in user who is NOT the admin: the section is theirs, not the admin's. */
function serveAsMember() {
  stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) => {
    if (url.endsWith("/api/me")) {
      return Promise.resolve(
        jsonResponse({ email: "member@example.com", is_admin: false, mode: "LIVE", dry_run_brake: false, ...SIGNED_UP }),
      );
    }
    if (url.includes("/api/notifications/unseen")) return Promise.resolve(jsonResponse({ kinds: [] }));
    if (url.includes("/api/notifications")) return Promise.resolve(jsonResponse({ items: [], next_cursor: null }));
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

describe("the Notifications section", () => {
  it("is routed at /notifications for a user who is not the admin", async () => {
    serveAsMember();
    renderAt(<AppRoutes />, "/notifications");
    expect(await screen.findByRole("heading", { level: 1, name: "Notifications" })).toBeInTheDocument();
  });

  it("takes /safety-events, which no longer has a page of its own, to /notifications", async () => {
    serveAsMember();
    renderAt(<AppRoutes />, "/safety-events");

    expect(await screen.findByRole("heading", { level: 1, name: "Notifications" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Safety events" })).not.toBeInTheDocument();
    const nav = screen.getAllByRole("navigation", { name: "Sections" })[0] as HTMLElement;
    expect(within(nav).getByRole("link", { name: "Notifications" })).toHaveAttribute("aria-current", "page");
  });

  it("is offered in both navigations, in place of Safety events, to a user who is not the admin", async () => {
    serveAsMember();
    renderAt(<AppRoutes />, "/");
    const navs = await screen.findAllByRole("navigation", { name: "Sections" });
    expect(navs.length).toBeGreaterThan(0);
    for (const nav of navs) {
      expect(within(nav).getByRole("link", { name: "Notifications" })).toHaveAttribute("href", "/notifications");
      expect(within(nav).queryByRole("link", { name: "Safety events" })).not.toBeInTheDocument();
      expect(within(nav).queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
    }
  });
});
