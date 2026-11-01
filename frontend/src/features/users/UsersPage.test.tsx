import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import { adminUser, jsonResponse, renderAt, resetExchangeScope, setViewport, stubApi, unlock } from "@/test/harness";

function serve(answer: () => Promise<Response>, me: Record<string, unknown> = {}) {
  return stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) => {
    if (url.endsWith("/api/admin/users")) return answer();
    if (url.endsWith("/api/me")) {
      return Promise.resolve(
        jsonResponse({ email: "owner@example.com", is_admin: true, mode: "LIVE", dry_run_brake: false, ...me }),
      );
    }
    return undefined;
  });
}

function open() {
  renderAt(<AppRoutes />, "/users");
}

async function rowOf(...users: Record<string, unknown>[]) {
  serve(() => Promise.resolve(jsonResponse(users)));
  open();
  return screen.findByTestId("admin-user-row");
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

describe("Users", () => {
  it("is titled, under its own heading", async () => {
    await rowOf(adminUser());

    expect(screen.getByRole("heading", { level: 1, name: "Users" })).toBeInTheDocument();
  });

  it("shows no exchange tabs: the list is of everyone, on every exchange", async () => {
    await rowOf(adminUser());

    expect(screen.queryByRole("navigation", { name: "Exchanges" })).not.toBeInTheDocument();
  });

  it("shows who a user is and their state", async () => {
    const row = await rowOf(adminUser());

    expect(within(row).getByTestId("admin-user-email")).toHaveTextContent("ana@example.com");
    expect(within(row).getByTestId("admin-user-name")).toHaveTextContent("Ana");
    expect(within(row).getByTestId("admin-user-mode")).toHaveTextContent("Live");
    expect(within(row).getByTestId("admin-user-keys")).toHaveTextContent("bybit");
    expect(within(row).getByTestId("admin-user-subscriptions")).toHaveTextContent("3");
    expect(within(row).getByTestId("admin-user-positions")).toHaveTextContent("2");
    expect(within(row).getByTestId("admin-user-seen")).toHaveTextContent("Oct 30, 2026, 12:34");
  });

  it("draws one row per user, in the order the server gave", async () => {
    serve(() =>
      Promise.resolve(jsonResponse([adminUser({ email: "a@example.com" }), adminUser({ email: "b@example.com" })])),
    );
    open();

    const rows = await screen.findAllByTestId("admin-user-row");
    expect(rows.map((row) => within(row).getByTestId("admin-user-email").textContent)).toEqual([
      "a@example.com",
      "b@example.com",
    ]);
  });

  it("says simulation in words", async () => {
    const row = await rowOf(adminUser({ mode: "SIMULATION" }));

    expect(within(row).getByTestId("admin-user-mode")).toHaveTextContent("Simulation");
  });

  it("says a user has chosen no name yet", async () => {
    const row = await rowOf(adminUser({ display_name: null }));

    expect(within(row).getByTestId("admin-user-name")).toHaveTextContent("No name yet");
  });

  it("lists every exchange with a key", async () => {
    const row = await rowOf(adminUser({ exchanges_with_key: ["binance", "bybit"] }));

    expect(within(row).getByTestId("admin-user-keys")).toHaveTextContent("binance, bybit");
  });

  it("says a user holds no key at all", async () => {
    const row = await rowOf(adminUser({ exchanges_with_key: [] }));

    expect(within(row).getByTestId("admin-user-keys")).toHaveTextContent("None");
  });

  it("tells an enabled pool with no key apart, naming the exchange, as a loss", async () => {
    const row = await rowOf(adminUser({ exchanges_with_no_key: ["binance", "bybit"] }));

    const fault = within(row).getByTestId("admin-user-no-key");
    expect(fault).toHaveTextContent("Enabled pool with no active key: binance, bybit");
    expect(fault).toHaveClass("text-loss");
  });

  it("says nothing of a fault when every pool has its key", async () => {
    const row = await rowOf(adminUser());

    expect(within(row).queryByTestId("admin-user-no-key")).not.toBeInTheDocument();
  });

  it("says the brake forces simulation over the modes shown", async () => {
    serve(() => Promise.resolve(jsonResponse([adminUser()])), { dry_run_brake: true });
    open();

    expect(await screen.findByText(i18n.t("users.brake"))).toBeInTheDocument();
  });

  it("says nothing of the brake when it is off", async () => {
    await rowOf(adminUser());

    expect(screen.queryByText(i18n.t("users.brake"))).not.toBeInTheDocument();
  });

  it("reads first, with no list", async () => {
    serve(() => new Promise<Response>(() => undefined));
    open();

    expect(await screen.findByText(i18n.t("users.loading"))).toBeInTheDocument();
    expect(screen.queryByTestId("admin-user-row")).not.toBeInTheDocument();
  });

  it("says a failed read is a failure, never an empty list", async () => {
    serve(() => Promise.resolve(jsonResponse({ detail: "boom" }, 500)));
    open();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(i18n.t("users.error"));
    expect(screen.queryByTestId("admin-user-row")).not.toBeInTheDocument();
  });

  it("speaks Spanish with its own words", async () => {
    await i18n.changeLanguage("es");
    const row = await rowOf(adminUser({ mode: "SIMULATION", exchanges_with_key: [], exchanges_with_no_key: ["bybit"], display_name: null }));

    expect(screen.getByRole("heading", { level: 1, name: "Usuarios" })).toBeInTheDocument();
    expect(within(row).getByTestId("admin-user-mode")).toHaveTextContent("Simulación");
    expect(within(row).getByTestId("admin-user-name")).toHaveTextContent("Sin nombre todavía");
    expect(within(row).getByTestId("admin-user-keys")).toHaveTextContent("Ninguna");
    expect(within(row).getByTestId("admin-user-no-key")).toHaveTextContent("Pool habilitado sin clave activa: bybit");
  });
});
