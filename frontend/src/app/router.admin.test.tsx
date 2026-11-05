import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import { adminUser, jsonResponse, renderAt, resetExchangeScope, setViewport, stubApi, unlock } from "@/test/harness";

// Past the real `SignInGate`, which lets every signed-in user in since PR G: what
// keeps these routes the admin's is `AdminRoute`.

function serve(isAdmin: boolean) {
  return stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) => {
    if (url.endsWith("/api/admin/users")) return Promise.resolve(jsonResponse([adminUser()]));
    if (url.endsWith("/api/me")) {
      return Promise.resolve(
        jsonResponse({ email: "a@example.com", is_admin: isAdmin, mode: "SIMULATION", dry_run_brake: false }),
      );
    }
    return undefined;
  });
}

function requestsTo(fetchMock: ReturnType<typeof stubApi>, path: string) {
  return fetchMock.mock.calls.filter(([input]) => String(input).includes(path));
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
  setViewport("wide");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the admin's routes, past the sign-in gate", () => {
  it.each([
    ["/users", "/api/admin/users"],
    ["/discrepancies", "/reconciliation/confirmed"],
  ])("answers anyone else not found at %s, and never asks for its data", async (path, read) => {
    const fetchMock = serve(false);
    renderAt(<AppRoutes />, path);

    expect(await screen.findByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
    expect(requestsTo(fetchMock, read)).toEqual([]);
  });

  it.each([
    ["/users", "Users"],
    ["/discrepancies", "Discrepancies"],
  ])("serves the admin %s", async (path, title) => {
    serve(true);
    renderAt(<AppRoutes />, path);

    expect(await screen.findByRole("heading", { level: 1, name: title })).toBeInTheDocument();
  });
});
