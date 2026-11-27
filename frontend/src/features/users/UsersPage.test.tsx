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

/** `count` users, numbered from 1 in the order the server gives them. */
function manyUsers(count: number) {
  return Array.from({ length: count }, (_, index) =>
    adminUser({ id: `user-${index + 1}`, email: `user${index + 1}@example.com` }),
  );
}

const emails = () =>
  screen.getAllByTestId("admin-user-row").map((row) => within(row).getByTestId("admin-user-email").textContent);

/** The tip a trigger shows on hover. */
function tipOf(trigger: HTMLElement): string | null {
  fireEvent.mouseEnter(trigger);
  const text = screen.getByRole("tooltip").textContent;
  fireEvent.mouseLeave(trigger);
  return text;
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
  it("says since when an account is suspended in its state dot, and that one that is not is active (L47)", async () => {
    serveSuspension([adminUser({ suspended_at: "2026-11-20T10:00:00Z" }), adminUser({ id: "u2", email: "b@example.com" })]);
    open();

    const rows = await screen.findAllByTestId("admin-user-row");
    const suspended = within(rows[0] as HTMLElement).getByTestId("admin-user-state");
    expect(suspended).toHaveAccessibleName("Suspended since Nov 20, 2026, 10:00");
    expect(suspended).toHaveClass("bg-loss");
    const active = within(rows[1] as HTMLElement).getByTestId("admin-user-state");
    expect(active).toHaveAccessibleName("Active");
    expect(active).toHaveClass("bg-gain");
    // The sentence is in the tip, not in the row (L47).
    expect(rows[0]).not.toHaveTextContent("Suspended since");
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

  it("offers Reactivate to a suspended account, and sends exactly {suspended: false} after confirming", async () => {
    const puts = serveSuspension([adminUser({ suspended_at: "2026-11-20T10:00:00Z" })]);
    open();
    const row = await screen.findByTestId("admin-user-row");

    expect(within(row).queryByRole("button", { name: "Suspend" })).toBeNull();
    fireEvent.click(within(row).getByRole("button", { name: "Reactivate" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Lift the suspension of ana@example.com?");
    expect(dialog).toHaveTextContent("They can open positions and subscribe again.");
    expect(puts).toEqual([]);

    fireEvent.click(within(dialog).getByRole("button", { name: "Reactivate" }));

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

  it("says You on the admin's own row, with no button", async () => {
    serveSuspension([adminUser({ email: "owner@example.com" }), adminUser({ id: "u2", email: "b@example.com" })]);
    open();

    const rows = await screen.findAllByTestId("admin-user-row");
    await waitFor(() => expect(within(rows[1] as HTMLElement).queryByRole("button", { name: "Suspend" })).not.toBeNull());
    expect(within(rows[0] as HTMLElement).queryByRole("button")).toBeNull();
    expect(within(rows[0] as HTMLElement).getByTestId("admin-user-self")).toHaveTextContent("You");
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
    expect(within(rows[0] as HTMLElement).getByTestId("admin-user-state")).toHaveAccessibleName(/^Suspendida desde /);
    expect(within(rows[1] as HTMLElement).getByTestId("admin-user-state")).toHaveAccessibleName("Activa");
    fireEvent.click(within(rows[0] as HTMLElement).getByRole("button", { name: "Reactivar" }));
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
    // The name the user chose is the e-mail's tip: the table has no Name column (L51).
    expect(tipOf(within(row).getByTestId("admin-user-email"))).toBe("Name: Ana");
    expect(within(row).getByTestId("admin-user-mode")).toHaveTextContent("Live");
    expect(within(row).getByTestId("admin-user-keys")).toHaveTextContent("Bybit");
    expect(within(row).getByTestId("admin-user-subscriptions")).toHaveTextContent("3");
    expect(within(row).getByTestId("admin-user-positions")).toHaveTextContent("2");
    expect(within(row).getByTestId("admin-user-seen")).toHaveTextContent("Oct 30, 2026, 12:34");
  });

  it("is a table at the 13 px of the panel's other tables, with My subscriptions' 8 px sides for its eight columns (L47, L51)", async () => {
    const row = await rowOf(adminUser());

    const table = screen.getByRole("table", { name: "Users" });
    expect(within(table).getAllByRole("columnheader").map((head) => head.textContent)).toEqual([
      "User",
      "Identity",
      "Mode",
      "Keys",
      "Subs.",
      "Positions",
      "Last sign-in",
      "Actions",
    ]);
    for (const cell of within(row).getAllByRole("cell")) expect(cell).toHaveClass("text-[13px]", "px-2");
    for (const head of within(table).getAllByRole("columnheader")) expect(head).toHaveClass("px-2");
  });

  it("shows the legal name, and the CUIT as people write it and the country in its tip (L47)", async () => {
    const row = await rowOf(adminUser());

    const identity = within(row).getByTestId("admin-user-identity");
    expect(identity).toHaveTextContent("Ana María Pérez");
    expect(row).not.toHaveTextContent("20-12345678-6");
    expect(tipOf(identity)).toBe("CUIT 20-12345678-6 · Argentina");
  });

  it("says a user has not signed up yet, the whole sentence in the tip", async () => {
    const row = await rowOf(adminUser({ identity: null }));

    const identity = within(row).getByTestId("admin-user-identity");
    expect(identity).toHaveTextContent("Not signed up");
    expect(tipOf(identity)).toBe("Not signed up yet");
  });

  it("shows the identity in Spanish too", async () => {
    await i18n.changeLanguage("es");
    const row = await rowOf(adminUser({ identity: null }));

    const identity = within(row).getByTestId("admin-user-identity");
    expect(identity).toHaveTextContent("Sin alta");
    expect(tipOf(identity)).toBe("Todavía no completó el alta");
  });

  it("shows a signed-up user's identity in Spanish", async () => {
    await i18n.changeLanguage("es");
    const row = await rowOf(adminUser());

    const identity = within(row).getByTestId("admin-user-identity");
    expect(identity).toHaveTextContent("Ana María Pérez");
    expect(tipOf(identity)).toBe("CUIT 20-12345678-6 · Argentina");
  });

  it("draws one row per user, in the order the server gave", async () => {
    serve(() =>
      Promise.resolve(jsonResponse([adminUser({ email: "a@example.com" }), adminUser({ id: "u2", email: "b@example.com" })])),
    );
    open();

    await screen.findAllByTestId("admin-user-row");
    expect(emails()).toEqual(["a@example.com", "b@example.com"]);
  });

  it("says simulation in words", async () => {
    const row = await rowOf(adminUser({ mode: "SIMULATION" }));

    expect(within(row).getByTestId("admin-user-mode")).toHaveTextContent("Simulation");
  });

  it("says a user has chosen no name", async () => {
    const row = await rowOf(adminUser({ display_name: null }));

    expect(tipOf(within(row).getByTestId("admin-user-email"))).toBe("No name");
  });

  it("lists every exchange with a key, by its proper name", async () => {
    const row = await rowOf(adminUser({ exchanges_with_key: ["binance", "bybit"] }));

    expect(within(row).getByTestId("admin-user-keys")).toHaveTextContent("Binance, Bybit");
  });

  it("marks keys on every enabled pool with a gain dot on the left (L48)", async () => {
    const row = await rowOf(adminUser());

    const mark = within(row).getByTestId("admin-user-keys-mark");
    expect(mark).toHaveAccessibleName("A key on every enabled pool");
    expect(mark).toHaveClass("bg-gain");
    expect(within(row).getByTestId("admin-user-keys").firstElementChild).toContainElement(mark);
  });

  it("says a user holds no key at all, with a grey dot (L48)", async () => {
    const row = await rowOf(adminUser({ exchanges_with_key: [] }));

    expect(within(row).getByTestId("admin-user-keys")).toHaveTextContent("None");
    const mark = within(row).getByTestId("admin-user-keys-mark");
    expect(mark).toHaveAccessibleName("No keys");
    expect(mark).toHaveClass("bg-ink-3");
  });

  it("puts the loss triangle in the dot's place for an enabled pool with no key, naming the exchange in its tip (L48)", async () => {
    const row = await rowOf(adminUser({ exchanges_with_no_key: ["binance", "bybit"] }));

    const fault = within(row).getByTestId("admin-user-no-key");
    expect(fault).toHaveClass("text-loss");
    expect(fault).toHaveAccessibleName("Enabled pool with no active key: Binance, Bybit");
    expect(within(row).queryByTestId("admin-user-keys-mark")).not.toBeInTheDocument();
    expect(within(row).getByTestId("admin-user-keys").firstElementChild).toContainElement(fault);
    expect(row).not.toHaveTextContent("Enabled pool");
  });

  it("says nothing of a fault when every pool has its key", async () => {
    const row = await rowOf(adminUser());

    expect(within(row).queryByTestId("admin-user-no-key")).not.toBeInTheDocument();
  });

  it("says the brake forces simulation over the modes shown, in an (i) beside Mode (L47)", async () => {
    serve(() => Promise.resolve(jsonResponse([adminUser()])), { dry_run_brake: true, ...SIGNED_UP });
    open();
    await screen.findByTestId("admin-user-row");

    const info = await screen.findByRole("img", { name: "Brake on" });
    expect(within(screen.getByRole("table")).getAllByRole("columnheader")[2]).toContainElement(info);
    expect(tipOf(info.parentElement as HTMLElement)).toBe(i18n.t("users.brake"));
  });

  it("lets the brake's tip leave the table's box, which clips nothing: a short list would scroll under it (L50)", async () => {
    serve(() => Promise.resolve(jsonResponse([adminUser()])), { dry_run_brake: true, ...SIGNED_UP });
    open();
    await screen.findByTestId("admin-user-row");

    const table = screen.getByRole("table");
    const box = table.parentElement as HTMLElement;
    expect(box.className).not.toMatch(/\boverflow-/);
    // Nothing clips the heading row to the box's 8 px corners any more, so its two outer cells round their own.
    const heads = within(table).getAllByRole("columnheader");
    expect(heads[0]).toHaveClass("rounded-tl-[7px]");
    expect(heads[heads.length - 1]).toHaveClass("rounded-tr-[7px]");
  });

  it("says nothing of the brake when it is off", async () => {
    await rowOf(adminUser());

    expect(screen.queryByRole("img", { name: "Brake on" })).not.toBeInTheDocument();
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
    expect(tipOf(within(row).getByTestId("admin-user-email"))).toBe("Sin nombre");
    expect(within(row).getByTestId("admin-user-keys")).toHaveTextContent("Ninguna");
    expect(within(row).getByTestId("admin-user-no-key")).toHaveAccessibleName("Pool habilitado sin clave activa: Bybit");
    expect(screen.getByTestId("admin-users-count")).toHaveTextContent("1 usuario");
    expect(screen.getByText("Página 1 de 1")).toBeInTheDocument();
  });
});

describe("Users: pages of 20 (L47)", () => {
  it("shows the first 20, the total in the card's header, and the page of how many", async () => {
    serve(() => Promise.resolve(jsonResponse(manyUsers(45))));
    open();
    await screen.findAllByTestId("admin-user-row");

    expect(emails()).toEqual(manyUsers(20).map((user) => user.email));
    expect(screen.getByTestId("admin-users-count")).toHaveTextContent("45 users");
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
  });

  it("moves a page forward and back, and stops at the last", async () => {
    const users = manyUsers(45);
    serve(() => Promise.resolve(jsonResponse(users)));
    open();
    await screen.findAllByTestId("admin-user-row");

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(emails()).toEqual(users.slice(20, 40).map((user) => user.email));
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(emails()).toEqual(users.slice(40).map((user) => user.email));
    expect(screen.getByText("Page 3 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(emails()).toEqual(users.slice(20, 40).map((user) => user.email));
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
  });

  it("says one user in the singular, and has both buttons off when one page holds everyone", async () => {
    await rowOf(adminUser());

    expect(screen.getByTestId("admin-users-count")).toHaveTextContent("1 user");
    expect(screen.getByText("Page 1 of 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });
});

describe("Users on a phone", () => {
  it("draws each user as a card with the same facts, and pages them the same way", async () => {
    setViewport("narrow");
    serve(() => Promise.resolve(jsonResponse(manyUsers(25))));
    open();
    await screen.findAllByTestId("admin-user-row");

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(20);
    const card = screen.getAllByTestId("admin-user-row")[0] as HTMLElement;
    expect(within(card).getByTestId("admin-user-email")).toHaveTextContent("user1@example.com");
    // A card has room for the name as a fact of its own.
    expect(within(card).getByTestId("admin-user-name")).toHaveTextContent("Ana");
    expect(within(card).getByTestId("admin-user-keys")).toHaveTextContent("Bybit");
    expect(within(card).getByRole("button", { name: "Suspend" })).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();
  });
});
