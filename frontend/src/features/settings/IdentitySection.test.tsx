import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DisplayNameSection } from "@/features/settings/DisplayNameSection";
import { IdentitySection } from "@/features/settings/IdentitySection";
import i18n from "@/shared/i18n";
import es from "@/shared/i18n/locales/es.json";
import { jsonResponse, lock, renderAt, resetExchangeScope, SIGNED_UP, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: false } } as const;
const PROFILE = { first_name: "Ana", last_name: "Peres", cuit: "20123456786", country: "AR" };
const ME = { email: "owner@example.com", is_admin: true, mode: "LIVE", dry_run_brake: false, ...SIGNED_UP };
const CONTACT_NOTE = "To correct your CUIT or your country, write to privacy@strategymanager.trade.";

/**
 * Settings for a user who signed up. A PUT of the name is recorded and answered by `outcome`: a refusal, or
 * `"saved"`, which stores the names sent with their spaces folded, so `/api/me` answers them from then on.
 */
function setup(
  profile: typeof PROFILE | null = PROFILE,
  outcome: Response | "saved" = "saved",
) {
  const sent: unknown[] = [];
  let stored = profile;
  stubApi(HEALTH, [], undefined, {}, (url, init) => {
    if (url.endsWith("/api/me/profile/name")) {
      const body = JSON.parse(String(init?.body)) as { first_name: string; last_name: string };
      sent.push(body);
      if (outcome !== "saved") return Promise.resolve(outcome);
      const fold = (name: string) => name.split(/\s+/).filter(Boolean).join(" ");
      stored = { ...PROFILE, first_name: fold(body.first_name), last_name: fold(body.last_name) };
      return Promise.resolve(jsonResponse({ ...ME, profile: stored }));
    }
    if (url.endsWith("/api/me")) return Promise.resolve(jsonResponse({ ...ME, profile: stored }));
    return undefined;
  });
  // The two forms of the name, as `AccountDetails` opens them under its card from `Edit name`.
  renderAt(
    <>
      <DisplayNameSection />
      <IdentitySection />
    </>,
    "/settings",
  );
  return { sent };
}

/** The section, once Settings has drawn its first one: missing, it fails on the assertion, not on a lookup. */
const section = async () => {
  await screen.findByRole("heading", { level: 2, name: "Profile" });
  const heading = screen.queryByRole("heading", { level: 2, name: "Your details" });
  expect(heading).not.toBeNull();
  return heading?.closest("section") as HTMLElement;
};
const firstName = async () => within(await section()).getByLabelText("First name") as HTMLInputElement;
const lastName = async () => within(await section()).getByLabelText("Last name") as HTMLInputElement;
const saveButton = async () => within(await section()).findByRole("button", { name: "Save" });

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

describe("the details given at sign-up, in Settings", () => {
  it("shows the names to edit, and the CUIT and the country to read only, with where to correct them", async () => {
    setup();
    const details = await section();

    expect((await firstName()).value).toBe("Ana");
    expect((await lastName()).value).toBe("Peres");
    expect(within(details).getByText("20-12345678-6")).toBeInTheDocument();
    expect(within(details).getByText("Argentina")).toBeInTheDocument();
    expect(within(details).queryByDisplayValue("20123456786")).toBeNull();
    expect(within(details).getAllByRole("textbox")).toHaveLength(2);
    expect(within(details).getByText(CONTACT_NOTE)).toBeInTheDocument();
    expect(await saveButton()).toBeDisabled();
  });

  it("sends both names, says it was saved, and shows them as the server stored them", async () => {
    const { sent } = setup();

    fireEvent.change(await lastName(), { target: { value: "  Pérez   Gómez " } });
    fireEvent.click(await saveButton());

    expect(await within(await section()).findByRole("button", { name: "Saved" })).toBeInTheDocument();
    expect(sent).toEqual([{ first_name: "Ana", last_name: "  Pérez   Gómez " }]);
    expect((await lastName()).value).toBe("Pérez Gómez");
  });

  it("sends nothing for a blank name", async () => {
    const { sent } = setup();

    fireEvent.change(await firstName(), { target: { value: "   " } });

    expect(await saveButton()).toBeDisabled();
    fireEvent.submit((await firstName()).closest("form") as HTMLFormElement);
    expect(sent).toEqual([]);
  });

  it("says which name was refused, and keeps what was typed", async () => {
    setup(
      PROFILE,
      jsonResponse({ detail: { error: "PROFILE_INVALID", field: "first_name", message: "no" } }, 422),
    );

    fireEvent.change(await firstName(), { target: { value: "Ana​" } });
    fireEvent.click(await saveButton());

    expect(await screen.findByText("Write between 1 and 80 characters.")).toBeInTheDocument();
    expect((await firstName()).value).toBe("Ana​");
    expect(await firstName()).toHaveAttribute("aria-invalid", "true");
  });

  it("says the names were not saved after any other refusal", async () => {
    setup(PROFILE, jsonResponse({ detail: { error: "SOMETHING_ELSE" } }, 500));

    fireEvent.change(await firstName(), { target: { value: "Beatriz" } });
    fireEvent.click(await saveButton());

    expect(await screen.findByRole("alert")).toHaveTextContent("The names were not saved. Try again.");
  });

  it("shows nothing for a user with no profile", async () => {
    setup(null);

    expect(await screen.findByRole("heading", { level: 2, name: "Profile" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 2, name: "Your details" })).toBeNull();
  });

  it("renders its texts in Spanish, to usted", async () => {
    setup();
    await act(() => i18n.changeLanguage("es"));

    await screen.findByRole("heading", { level: 2, name: "Perfil" });
    expect(screen.queryByRole("heading", { level: 2, name: "Sus datos" })).not.toBeNull();
    expect(screen.getByText("Para corregir su CUIT o su país, escriba a privacy@strategymanager.trade.")).toBeInTheDocument();
    expect(await screen.findByLabelText(es.signUp.firstName)).toBeInTheDocument();
  });
});
