import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import {
  adminUser,
  jsonResponse,
  renderAt,
  resetExchangeScope,
  setViewport,
  SIGNED_UP,
  stubApi,
  unlock,
} from "@/test/harness";

function serve(answer: () => Promise<Response>, me: Record<string, unknown> = {}) {
  return stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) => {
    if (url.endsWith("/api/admin/users")) return answer();
    if (url.endsWith("/api/me")) {
      return Promise.resolve(
        jsonResponse({ email: "owner@example.com", is_admin: true, mode: "LIVE", dry_run_brake: false, ...SIGNED_UP, ...me }),
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

interface Put {
  url: string;
  body: unknown;
}

/** The list answers `users`; a PUT to a suspension is recorded and answered with `answer`. */
function serveSuspension(users: Record<string, unknown>[], answer: () => Response = () => jsonResponse(null, 204)) {
  const puts: Put[] = [];
  stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url, init) => {
    if (url.endsWith("/suspension") && init?.method === "PUT") {
      puts.push({ url, body: JSON.parse(String(init.body)) });
      return Promise.resolve(answer());
    }
    if (url.endsWith("/api/admin/users")) return Promise.resolve(jsonResponse(users));
    if (url.endsWith("/api/me")) {
      return Promise.resolve(
        jsonResponse({ email: "owner@example.com", is_admin: true, mode: "LIVE", dry_run_brake: false, ...SIGNED_UP }),
      );
    }
    return undefined;
  });
  return puts;
}

describe("Users: suspension (public-site LS9)", () => {
  it("says since when an account is suspended, and nothing for one that is not", async () => {
    serveSuspension([adminUser({ suspended_at: "2026-11-20T10:00:00Z" }), adminUser({ id: "u2", email: "b@example.com" })]);
    open();

    const rows = await screen.findAllByTestId("admin-user-row");
    expect(rows[0]).toHaveTextContent("Suspended since Nov 20, 2026, 10:00");
    expect(rows[1]).not.toHaveTextContent("Suspended since");
  });

  it("offers Suspend, asks first, and sends exactly {suspended: true} only after confirming", async () => {
    const puts = serveSuspension([adminUser()]);
    open();
    const row = await screen.findByTestId("admin-user-row");

    fireEvent.click(within(row).getByRole("button", { name: "Suspend" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Suspend ana@example.com?");
    expect(dialog).toHaveTextContent(
      "They will open nothing new, and the strategies they publish will stop opening for every subscriber. Their closes keep running.",
    );
    expect(puts).toEqual([]);

    fireEvent.click(within(dialog).getByRole("button", { name: "Suspend" }));

    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]?.url).toMatch(/\/api\/admin\/users\/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa\/suspension$/);
    expect(puts[0]?.body).toEqual({ suspended: true });
  });

  it("offers Lift suspension to a suspended account, and sends exactly {suspended: false} after confirming", async () => {
    const puts = serveSuspension([adminUser({ suspended_at: "2026-11-20T10:00:00Z" })]);
    open();
    const row = await screen.findByTestId("admin-user-row");

    expect(within(row).queryByRole("button", { name: "Suspend" })).toBeNull();
    fireEvent.click(within(row).getByRole("button", { name: "Lift suspension" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Lift the suspension of ana@example.com?");
    expect(dialog).toHaveTextContent("They can open positions and subscribe again.");
    expect(puts).toEqual([]);

    fireEvent.click(within(dialog).getByRole("button", { name: "Lift suspension" }));

    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]?.body).toEqual({ suspended: false });
  });

  it("sends nothing when the dialog is cancelled", async () => {
    const puts = serveSuspension([adminUser()]);
    open();
    const row = await screen.findByTestId("admin-user-row");

    fireEvent.click(within(row).getByRole("button", { name: "Suspend" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(puts).toEqual([]);
  });

  it("offers no button on the admin's own row", async () => {
    serveSuspension([adminUser({ email: "owner@example.com" }), adminUser({ id: "u2", email: "b@example.com" })]);
    open();

    const rows = await screen.findAllByTestId("admin-user-row");
    await waitFor(() => expect(within(rows[1] as HTMLElement).queryByRole("button", { name: "Suspend" })).not.toBeNull());
    expect(within(rows[0] as HTMLElement).queryByRole("button")).toBeNull();
  });

  it.each([
    [409, { error: "CANNOT_SUSPEND_YOURSELF" }, "You cannot suspend your own account."],
    [404, { error: "USER_NOT_FOUND" }, "The suspension could not be changed."],
    [409, { error: "ACCOUNT_CHANGED" }, "The account changed while it was being suspended. Try again."],
    [500, "boom", "The suspension could not be changed."],
  ])("says a %s refusal inline, as an alert", async (status, detail, message) => {
    serveSuspension([adminUser()], () => jsonResponse({ detail }, status));
    open();
    const row = await screen.findByTestId("admin-user-row");

    fireEvent.click(within(row).getByRole("button", { name: "Suspend" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Suspend" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("speaks Spanish with its own words", async () => {
    await i18n.changeLanguage("es");
    serveSuspension([adminUser({ id: "u2", suspended_at: "2026-11-20T10:00:00Z" }), adminUser()]);
    open();

    const rows = await screen.findAllByTestId("admin-user-row");
    expect(rows[0]).toHaveTextContent("Suspendida desde");
    fireEvent.click(within(rows[0] as HTMLElement).getByRole("button", { name: "Levantar la suspensión" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("¿Levantar la suspensión de ana@example.com?");
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    fireEvent.click(within(rows[1] as HTMLElement).getByRole("button", { name: "Suspender" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("¿Suspender a ana@example.com?");
  });
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

  it("shows the identity the user gave at sign-up, with the CUIT as people write it", async () => {
    const row = await rowOf(adminUser());

    expect(row).toHaveTextContent("Ana María Pérez");
    expect(row).toHaveTextContent("20-12345678-6");
    expect(row).toHaveTextContent("Argentina");
  });

  it("says a user has not signed up yet when there is no identity", async () => {
    const row = await rowOf(adminUser({ identity: null }));

    expect(row).toHaveTextContent("Not signed up yet");
  });

  it("shows the identity in Spanish too", async () => {
    await i18n.changeLanguage("es");
    const row = await rowOf(adminUser({ identity: null }));

    expect(row).toHaveTextContent("Todavía no completó el alta");
  });

  it("shows a signed-up user's identity in Spanish", async () => {
    await i18n.changeLanguage("es");
    const row = await rowOf(adminUser());

    expect(row).toHaveTextContent("Ana María Pérez · CUIT 20-12345678-6 · Argentina");
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
    serve(() => Promise.resolve(jsonResponse([adminUser()])), { dry_run_brake: true, ...SIGNED_UP });
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
