import { screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminRoute } from "@/shared/auth/AdminRoute";
import { AppShell } from "@/shared/layout/AppShell";
import { BottomNav } from "@/shared/layout/BottomNav";
import { SideNav } from "@/shared/layout/SideNav";
import { jsonResponse, renderAt, stubApi, unlock } from "@/test/harness";

const USER = { email: "a@example.com", mode: "SIMULATION", dry_run_brake: true };

function serveMe(answer: () => Promise<Response>) {
  return stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) =>
    url.endsWith("/api/me") ? answer() : undefined,
  );
}

function asUser(isAdmin: boolean) {
  return serveMe(() => Promise.resolve(jsonResponse({ ...USER, is_admin: isAdmin })));
}

function bothNavs() {
  return renderAt(
    <>
      <SideNav />
      <BottomNav />
    </>,
    "/",
  );
}

function navs() {
  return screen.getAllByRole("navigation", { name: "Sections" });
}

function requestsTo(fetchMock: ReturnType<typeof stubApi>, path: string) {
  return fetchMock.mock.calls.filter(([input]) => String(input).includes(path));
}

beforeEach(() => {
  unlock();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("what the navigation offers", () => {
  it("offers the admin Discrepancies and Users in both navigations", async () => {
    asUser(true);
    bothNavs();

    await screen.findAllByRole("link", { name: "Users" });
    for (const nav of navs()) {
      expect(within(nav).getByRole("link", { name: "Discrepancies" })).toHaveAttribute("href", "/discrepancies");
      expect(within(nav).getByRole("link", { name: "Users" })).toHaveAttribute("href", "/users");
    }
  });

  it("offers the admin every section, in order", async () => {
    asUser(true);
    bothNavs();

    await screen.findAllByRole("link", { name: "Users" });
    for (const nav of navs()) {
      expect(within(nav).getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
        "/",
        "/strategies",
        "/discrepancies",
        "/users",
        "/settings",
      ]);
    }
  });

  it("offers anyone else neither, in either navigation, and never reads the discrepancies", async () => {
    const fetchMock = asUser(false);
    bothNavs();

    await waitFor(() => expect(requestsTo(fetchMock, "/api/me").length).toBeGreaterThan(0));
    await new Promise((resolve) => setTimeout(resolve, 0));
    for (const nav of navs()) {
      expect(within(nav).getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
        "/",
        "/strategies",
        "/settings",
      ]);
    }
    expect(requestsTo(fetchMock, "/reconciliation/confirmed")).toEqual([]);
  });

  it("offers neither before it knows who is signed in", () => {
    serveMe(() => new Promise<Response>(() => undefined));
    bothNavs();

    for (const nav of navs()) {
      expect(within(nav).getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
        "/",
        "/strategies",
        "/settings",
      ]);
    }
  });

  it("offers neither when it cannot tell", async () => {
    const fetchMock = serveMe(() => Promise.resolve(jsonResponse({ detail: "boom" }, 500)));
    bothNavs();

    await waitFor(() => expect(requestsTo(fetchMock, "/api/me").length).toBeGreaterThan(0));
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
  });

  it("keeps the badge's read for the admin", async () => {
    const fetchMock = stubApi({ kind: "ok", body: {} });
    bothNavs();

    await waitFor(() => expect(requestsTo(fetchMock, "/reconciliation/confirmed").length).toBeGreaterThan(0));
  });
});

function adminPage() {
  return renderAt(
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<p>overview body</p>} />
        <Route element={<AdminRoute />}>
          <Route path="users" element={<p>only the admin</p>} />
        </Route>
      </Route>
    </Routes>,
    "/users",
  );
}

function adminRouteAlone() {
  return renderAt(
    <Routes>
      <Route element={<AdminRoute />}>
        <Route path="users" element={<p>only the admin</p>} />
      </Route>
    </Routes>,
    "/users",
  );
}

describe("the pages only the admin has", () => {
  it("serves the admin the page", async () => {
    asUser(true);
    adminPage();

    expect(await screen.findByText("only the admin")).toBeInTheDocument();
  });

  it("answers anyone else not found, by the route and not only by the gate", async () => {
    asUser(false);
    adminRouteAlone();

    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.queryByText("only the admin")).not.toBeInTheDocument();
  });

  it("draws nothing before it knows who is signed in", () => {
    serveMe(() => new Promise<Response>(() => undefined));
    adminRouteAlone();

    expect(screen.queryByText("only the admin")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Page not found" })).not.toBeInTheDocument();
  });
});
