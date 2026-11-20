import { onlineManager } from "@tanstack/react-query";
import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsPage } from "@/features/settings/SettingsPage";
import { useAccountDeletedStore } from "@/shared/account/account-deleted";
import i18n from "@/shared/i18n";
import { jsonResponse, lock, renderAt, resetExchangeScope, SIGNED_UP, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: false } } as const;
const EMAIL = "someone@example.com";
const ME = { email: EMAIL, is_admin: false, mode: "LIVE", dry_run_brake: false, ...SIGNED_UP, display_name: "Ana" };

const NO_CONTENT = { ok: true, status: 204, json: () => Promise.reject(new Error("no body")) } as unknown as Response;

/** Settings for a signed-in user. Each DELETE of `/api/me` is counted and answered by `answer`. */
function setup(answer: Response | Promise<Response> = NO_CONTENT) {
  let deletes = 0;
  stubApi(HEALTH, [], undefined, {}, (url, init) => {
    if (url.endsWith("/api/me") && init?.method === "DELETE") {
      deletes += 1;
      return Promise.resolve(answer);
    }
    if (url.endsWith("/api/me")) return Promise.resolve(jsonResponse(ME));
    return undefined;
  });
  renderAt(<SettingsPage />, "/settings");
  return { deletes: () => deletes };
}

const section = () => screen.findByRole("region", { name: "Delete account" });
const openDialog = async () =>
  fireEvent.click(await within(await section()).findByRole("button", { name: "Delete account" }));
const dialog = () => screen.findByRole("dialog", { name: "Delete your account?" });
const typeEmail = async (value: string) =>
  fireEvent.change(within(await dialog()).getByLabelText("Your e-mail"), { target: { value } });
const confirmButton = async () => within(await dialog()).getByRole("button", { name: "Delete account" });

beforeEach(() => {
  unlock();
  resetExchangeScope();
  useAccountDeletedStore.setState({ deleted: false });
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  useAccountDeletedStore.setState({ deleted: false });
  // A deletion keeps every query paused for good; the next test starts online again.
  onlineManager.setOnline(true);
  await act(() => i18n.changeLanguage("en"));
});

describe("deleting the account, in Settings", () => {
  it("is the last section of the page, and says what is erased, closed and kept", async () => {
    setup();
    const region = await section();

    const headings = screen.getAllByRole("heading", { level: 2 });
    expect(headings[headings.length - 1]).toHaveTextContent("Delete account");
    expect(region).toHaveTextContent("Erased: your e-mail, your display name and every API key.");
    expect(region).toHaveTextContent(
      "Closed: your strategies are archived and made private, and every subscription to them ends, yours included. Your subscriptions to other strategies end too, and any simulated position on them is closed at market.",
    );
    expect(region).toHaveTextContent("Kept, without your name: your trades and their records, which others depend on.");
    expect(region).toHaveTextContent(
      "It cannot be done while you hold a real position, or anyone holds a position on one of your strategies.",
    );
  });

  it("sends nothing on opening, and asks for the e-mail before it can delete", async () => {
    const api = setup();
    await openDialog();

    expect(await confirmButton()).toBeDisabled();
    await typeEmail("someone@example.co");
    expect(await confirmButton()).toBeDisabled();
    // The e-mail as typed, with its case and stray spaces, is the e-mail.
    await typeEmail("  Someone@Example.com ");
    expect(await confirmButton()).toBeEnabled();
    expect(api.deletes()).toBe(0);
    // The safe button has the focus.
    expect(within(await dialog()).getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("deletes once on the confirm, and the panel then knows the account is gone", async () => {
    const api = setup();
    await openDialog();
    await typeEmail(EMAIL);

    await act(async () => fireEvent.click(await confirmButton()));

    expect(api.deletes()).toBe(1);
    expect(useAccountDeletedStore.getState().deleted).toBe(true);
  });

  it("lists every position that refuses it, and keeps the account", async () => {
    setup(
      jsonResponse(
        {
          detail: {
            error: "ACCOUNT_HOLDS_POSITIONS",
            message: "x",
            symbols: ["STXUSDT", "ETHUSDT"],
            strategies: [
              { id: "s-1", name: "BTC 4h", symbols: ["BTCUSDT"] },
              { id: "s-2", name: "SOL 1h", symbols: [] },
            ],
          },
        },
        409,
      ),
    );
    await openDialog();
    await typeEmail(EMAIL);

    await act(async () => fireEvent.click(await confirmButton()));

    const alert = within(await dialog()).getByRole("alert");
    expect(alert).toHaveTextContent("Your account cannot be deleted while a position is open.");
    expect(within(alert).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Your positions: STXUSDT, ETHUSDT",
      "BTC 4h: BTCUSDT",
      "SOL 1h: something is still held",
    ]);
    expect(useAccountDeletedStore.getState().deleted).toBe(false);
  });

  it("asks to try again when the account changed, or the answer was not understood", async () => {
    setup(jsonResponse({ detail: { error: "ACCOUNT_CHANGED", message: "x" } }, 409));
    await openDialog();
    await typeEmail(EMAIL);
    await act(async () => fireEvent.click(await confirmButton()));
    expect(within(await dialog()).getByRole("alert")).toHaveTextContent(
      "Something changed while the account was being deleted. Try again.",
    );
  });

  it("says when the answer was not understood", async () => {
    setup(jsonResponse({ detail: "boom" }, 500));
    await openDialog();
    await typeEmail(EMAIL);
    await act(async () => fireEvent.click(await confirmButton()));
    expect(within(await dialog()).getByRole("alert")).toHaveTextContent("The account could not be deleted. Try again.");
    expect(useAccountDeletedStore.getState().deleted).toBe(false);
  });

  it("cancels without sending anything", async () => {
    const api = setup();
    await openDialog();
    await typeEmail(EMAIL);

    fireEvent.click(within(await dialog()).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(api.deletes()).toBe(0);
  });

  it("reads every word in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    setup();
    const region = await screen.findByRole("region", { name: "Eliminar cuenta" });

    expect(region).toHaveTextContent("Se borran: su e-mail, su nombre visible y todas sus claves API.");
    fireEvent.click(within(region).getByRole("button", { name: "Eliminar cuenta" }));
    const opened = await screen.findByRole("dialog", { name: "¿Eliminar su cuenta?" });
    expect(within(opened).getByLabelText("Su e-mail")).toBeInTheDocument();
    expect(opened).toHaveTextContent("Esto no se puede deshacer. Escriba su e-mail para confirmar.");
  });
});
