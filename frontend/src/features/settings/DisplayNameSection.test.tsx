import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsPage } from "@/features/settings/SettingsPage";
import i18n from "@/shared/i18n";
import { jsonResponse, lock, renderAt, resetExchangeScope, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: false } } as const;
const EMAIL = "owner@example.com";
const ME = { email: EMAIL, is_admin: true, mode: "LIVE", dry_run_brake: false };

/**
 * Settings with a stored name. A PUT is recorded and answered by `outcome`: a refusal, or `"saved"`, which stores
 * the name sent, trimmed, so `/api/me` answers it from then on. `meReads` counts the reads of who is signed in.
 */
function setup(stored: string | null, outcome: Response | Promise<Response> | "saved" = "saved") {
  const sent: unknown[] = [];
  let reads = 0;
  let name = stored;
  stubApi(HEALTH, [], undefined, {}, (url, init) => {
    if (url.endsWith("/api/me/display-name")) {
      const body = JSON.parse(String(init?.body)) as { display_name: string };
      sent.push(body);
      if (outcome !== "saved") return Promise.resolve(outcome);
      name = body.display_name.trim();
      return Promise.resolve(jsonResponse({ ...ME, display_name: name }));
    }
    if (url.endsWith("/api/me")) {
      reads += 1;
      return Promise.resolve(jsonResponse({ ...ME, display_name: name }));
    }
    return undefined;
  });
  renderAt(<SettingsPage />, "/settings");
  return { sent, meReads: () => reads };
}

const field = () => screen.findByLabelText("Display name") as Promise<HTMLInputElement>;
const saveButton = () => screen.findByRole("button", { name: "Save name" });

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

describe("the display name, in Settings", () => {
  it("shows the stored name, and asks for nothing while it does not change", async () => {
    setup("Ana");

    expect((await field()).value).toBe("Ana");
    expect(await saveButton()).toBeDisabled();
    expect(screen.queryByText(/Until you choose a name/)).toBeNull();
  });

  it("says what is missing while there is no name", async () => {
    setup(null);

    expect((await field()).value).toBe("");
    expect(await saveButton()).toBeDisabled();
    expect(
      screen.getByText(
        "Until you choose a name, a strategy cannot turn public and your public strategies stay off the public list.",
      ),
    ).toBeInTheDocument();
  });

  it("says what the name is for and that the e-mail stays private", async () => {
    setup(null);

    await field();

    expect(
      screen.getByText("Other users see this name beside your public strategies. They never see your e-mail."),
    ).toBeInTheDocument();
    expect(screen.getByText("3 to 30 characters, with no @. You can change it later, but not remove it.")).toBeInTheDocument();
  });

  it("sends the name, says it was saved, and shows the one the server stored", async () => {
    const { sent } = setup(null);
    const input = await field();

    fireEvent.change(input, { target: { value: "Ana" } });
    fireEvent.click(await saveButton());

    await waitFor(() => expect(sent).toEqual([{ display_name: "Ana" }]));
    expect(await screen.findByText("Name saved.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    await waitFor(() => expect(screen.queryByText(/Until you choose a name/)).toBeNull());
    expect((await field()).value).toBe("Ana");
    expect(await saveButton()).toBeDisabled();
  });

  it("says it was saved from a region that was already there, so it is announced", async () => {
    setup(null);
    const input = await field();
    const region = within(input.closest("section") as HTMLElement).getByRole("status");
    expect(region).toBeEmptyDOMElement();

    fireEvent.change(input, { target: { value: "Ana" } });
    fireEvent.click(await saveButton());

    await waitFor(() => expect(region).toHaveTextContent("Name saved."));
  });

  it("shows the name as the server stored it, not as it was typed", async () => {
    setup(null);
    const input = await field();

    fireEvent.change(input, { target: { value: "  Ana  " } });
    fireEvent.click(await saveButton());

    await waitFor(() => expect(input.value).toBe("Ana"));
  });

  it("sends one name while one is on its way", async () => {
    let answer: (response: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      answer = resolve;
    });
    const { sent } = setup(null, pending);
    const input = await field();
    fireEvent.change(input, { target: { value: "Ana" } });
    const form = input.closest("form") as HTMLFormElement;

    fireEvent.submit(form);
    expect(await screen.findByRole("button", { name: "Saving…" })).toBeDisabled();
    fireEvent.submit(form);
    answer(jsonResponse(ME));

    expect(await screen.findByText("Name saved.")).toBeInTheDocument();
    expect(sent).toHaveLength(1);
  });

  it("says the name was not saved at a 401, and does not read who is signed in again", async () => {
    const { meReads } = setup("Carla", jsonResponse({ detail: "expired" }, 401));
    const input = await field();
    const before = meReads();

    fireEvent.change(input, { target: { value: "Ana" } });
    fireEvent.click(await saveButton());

    expect(await screen.findByRole("alert")).toHaveTextContent("The name was not saved. Try again.");
    expect(meReads()).toBe(before);
  });

  it("reads who is signed in again after a refusal: the stored name may have changed", async () => {
    const { meReads } = setup("Carla", jsonResponse({ detail: { error: "DISPLAY_NAME_TAKEN", message: "m" } }, 409));
    const input = await field();
    const before = meReads();

    fireEvent.change(input, { target: { value: "Ana" } });
    fireEvent.click(await saveButton());

    await screen.findByRole("alert");
    expect(meReads()).toBeGreaterThan(before);
  });

  it("submits with Enter too", async () => {
    const { sent } = setup(null);
    const input = await field();

    fireEvent.change(input, { target: { value: "Ana" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    await waitFor(() => expect(sent).toEqual([{ display_name: "Ana" }]));
  });

  it("sends nothing for a blank name or an unchanged one", async () => {
    const { sent } = setup("Ana");
    const input = await field();

    fireEvent.change(input, { target: { value: "   " } });
    expect(await saveButton()).toBeDisabled();
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    fireEvent.change(input, { target: { value: " Ana " } });
    expect(await saveButton()).toBeDisabled();
    fireEvent.submit(input.closest("form") as HTMLFormElement);

    expect(sent).toEqual([]);
  });

  it.each([
    ["taken", jsonResponse({ detail: { error: "DISPLAY_NAME_TAKEN", message: "m" } }, 409), "That name is taken. Choose another."],
    [
      "invalid",
      jsonResponse({ detail: { error: "DISPLAY_NAME_INVALID", message: "m" } }, 422),
      "That name is not valid: 3 to 30 characters, with no @ and no invisible characters.",
    ],
    ["failed", jsonResponse({ detail: "boom" }, 500), "The name was not saved. Try again."],
  ])("keeps what was typed and says so when it is %s", async (_label, response, text) => {
    setup("Carla", response);
    const input = await field();

    fireEvent.change(input, { target: { value: "Ana" } });
    fireEvent.click(await saveButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(input.value).toBe("Ana");
    expect(screen.queryByText("Name saved.")).toBeNull();
  });

  it("drops a refusal as soon as the name is edited", async () => {
    setup(null, jsonResponse({ detail: { error: "DISPLAY_NAME_TAKEN", message: "m" } }, 409));
    const input = await field();
    fireEvent.change(input, { target: { value: "Ana" } });
    fireEvent.click(await saveButton());
    await screen.findByRole("alert");

    fireEvent.change(input, { target: { value: "Anita" } });

    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("renders its texts in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    setup(null);

    await screen.findByLabelText("Nombre visible");

    expect(screen.getByRole("heading", { name: "Su nombre" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar nombre" })).toBeInTheDocument();
    expect(
      screen.getByText("Otros usuarios ven este nombre junto a sus estrategias públicas. Nunca ven su e-mail."),
    ).toBeInTheDocument();
    expect(screen.getByText("De 3 a 30 caracteres, sin @. Puede cambiarlo después, pero no quitarlo.")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Hasta que elija un nombre, una estrategia no puede pasar a pública y las que ya lo son no aparecen en la lista pública.",
      ),
    ).toBeInTheDocument();
  });

  it.each([
    ["taken", jsonResponse({ detail: { error: "DISPLAY_NAME_TAKEN", message: "m" } }, 409), "Ese nombre ya está en uso. Elija otro."],
    [
      "invalid",
      jsonResponse({ detail: { error: "DISPLAY_NAME_INVALID", message: "m" } }, 422),
      "Ese nombre no es válido: de 3 a 30 caracteres, sin @ y sin caracteres invisibles.",
    ],
    ["failed", jsonResponse({ detail: "boom" }, 500), "El nombre no se guardó. Inténtelo de nuevo."],
  ])("says %s in Spanish", async (_label, response, text) => {
    await act(() => i18n.changeLanguage("es"));
    setup(null, response);
    const input = await screen.findByLabelText("Nombre visible");

    fireEvent.change(input, { target: { value: "Ana" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar nombre" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });
});
