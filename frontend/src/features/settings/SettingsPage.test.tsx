import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import { jsonResponse, lock, pool, renderAt, resetExchangeScope, SIGNED_UP, storedKey, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const PROFILE = { first_name: "María", last_name: "Gómez", cuit: "27123456780", country: "AR" };

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

/** Mi cuenta (S4, ex7): the person's data, the mode, the language and the account's deletion. The keys moved. */
describe("My account", () => {
  function mount(me: Record<string, unknown> = {}) {
    const fetchMock = stubApi(
      HEALTH,
      [],
      { kind: "ok", body: [pool("bybit")] },
      {},
      (url) =>
        url.endsWith("/api/me")
          ? Promise.resolve(
              jsonResponse({
                email: "owner@example.com",
                is_admin: false,
                mode: "SIMULATION",
                dry_run_brake: false,
                ...SIGNED_UP,
                display_name: "mariag",
                profile: PROFILE,
                ...me,
              }),
            )
          : undefined,
      {},
      { kind: "ok", body: [storedKey("bybit")] },
    );
    renderAt(<AppRoutes />, "/settings");
    return fetchMock;
  }

  it("keeps the title and subtitle of ex7 and ends with the deletion of the account", async () => {
    mount();

    expect(await screen.findByRole("heading", { level: 1, name: "My account" })).toBeInTheDocument();
    expect(screen.getByText(en.pageHeader.account)).toBeInTheDocument();
    expect(en.pageHeader.account).toBe("Review your details and choose the panel's mode and language.");
    expect(await screen.findByRole("heading", { level: 2, name: "Delete account" })).toBeInTheDocument();
  });

  it("writes the subtitle of ex7 in Spanish", async () => {
    await i18n.changeLanguage("es");
    mount();

    expect(await screen.findByText("Revise sus datos y elija el modo y el idioma del panel.")).toBeInTheDocument();
  });

  it("holds four cards in the order of ex7: the data, the mode, the language, the deletion", async () => {
    mount();

    await screen.findByRole("heading", { level: 2, name: "Mode" });
    const titles = screen
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent)
      .filter((text) => ["Your data", "Mode", "Language", "Delete account"].includes(text ?? ""));
    expect(titles).toEqual(["Your data", "Mode", "Language", "Delete account"]);
  });

  it("draws the deletion card as ex7 does: a loss-coloured title and a loss-bordered card, apart from the others", async () => {
    mount();

    const heading = await screen.findByRole("heading", { level: 2, name: "Delete account" });
    expect(heading).toHaveClass("text-loss");
    expect(heading.closest("section")).toHaveClass("border-loss/40", "mt-4");
    // The other titles stay in ink.
    expect(screen.getByRole("heading", { level: 2, name: "Mode" })).toHaveClass("text-ink");
    expect(screen.getByRole("heading", { level: 2, name: "Mode" }).closest("section")).toHaveClass("border-rule");
  });

  it("lists the data: the display name and the name, then the CUIT and the country with a lock, and the note", async () => {
    mount();

    const card = (await screen.findByRole("heading", { level: 2, name: "Your data" })).closest("section") as HTMLElement;
    expect(within(card).getByText("Display name")).toBeInTheDocument();
    expect(within(card).getByText("mariag")).toBeInTheDocument();
    expect(within(card).getByText("Name")).toBeInTheDocument();
    expect(within(card).getByText("María Gómez")).toBeInTheDocument();
    expect(within(card).getByText("CUIT or CUIL")).toBeInTheDocument();
    expect(within(card).getByText("27-12345678-0")).toHaveClass("font-mono");
    expect(within(card).getByText("Country of residence")).toBeInTheDocument();
    expect(within(card).getByText("Argentina")).toBeInTheDocument();
    const locks = within(card).getAllByLabelText("Cannot be changed here");
    expect(locks).toHaveLength(2);
    expect(
      within(card).getByText("You can only change your name. The CUIT and the country cannot be changed from the panel."),
    ).toBeInTheDocument();
  });

  it("opens the forms of the name under the card from `Edit name`, and closes them again", async () => {
    mount();
    expect(screen.queryByRole("heading", { level: 2, name: "Profile" })).not.toBeInTheDocument();

    const edit = await screen.findByRole("button", { name: "Edit name" });
    expect(edit).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(edit);

    expect(edit).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByRole("heading", { level: 2, name: "Profile" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Your details" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close editing" }));
    expect(screen.queryByRole("heading", { level: 2, name: "Profile" })).not.toBeInTheDocument();
  });

  it("draws the Mode card with the switch of Live and Simulation, and the Language card with Español and English", async () => {
    mount();

    expect(await screen.findByRole("radiogroup", { name: "Trading mode" })).toBeInTheDocument();
    const language = screen.getByRole("radiogroup", { name: "Language" });
    expect(within(language).getAllByRole("radio").map((item) => [item.textContent, item.getAttribute("aria-checked")])).toEqual(
      [
        ["Español", "false"],
        ["English", "true"],
      ],
    );
    expect(screen.getByText("Language of the interface.")).toBeInTheDocument();
  });

  it("changes the language of the panel when the other option of the switch is pressed, in both directions", async () => {
    mount();
    const group = await screen.findByRole("radiogroup", { name: "Language" });

    fireEvent.click(within(group).getByRole("radio", { name: "Español" }));

    await waitFor(() => expect(i18n.resolvedLanguage).toBe("es"));
    expect(await screen.findByRole("heading", { level: 2, name: "Idioma" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Español" })).toHaveAttribute("aria-checked", "true");

    fireEvent.click(screen.getByRole("radio", { name: "English" }));

    await waitFor(() => expect(i18n.resolvedLanguage).toBe("en"));
    expect(await screen.findByRole("heading", { level: 2, name: "Language" })).toBeInTheDocument();
  });

  it("keeps the mode switch of the account inside the Mode card, so the badge on top only shows it", async () => {
    mount({ mode: "LIVE" });

    const card = (await screen.findByRole("heading", { level: 2, name: "Mode" })).closest("section") as HTMLElement;
    expect(await within(card).findByRole("radio", { name: "Live" })).toHaveAttribute("aria-checked", "true");
    expect(within(card).getByRole("radio", { name: "Simulation" })).toBeInTheDocument();
  });

  it("draws no key card, no key section and no `Link exchange` action: the keys live in Link exchange", async () => {
    mount();
    await screen.findByRole("heading", { level: 2, name: "Delete account" });

    expect(screen.queryByRole("heading", { level: 2, name: "Exchange keys" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3 })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Link exchange" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^(Add|Replace|Delete) key/ })).not.toBeInTheDocument();
  });

  it("never reads the keys or the pools", async () => {
    const fetchMock = mount();
    await screen.findByRole("heading", { level: 2, name: "Delete account" });
    // The shell reads what it needs; the page itself asks for no key.
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(0));

    const settingsReads = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/credentials"));
    expect(settingsReads).toEqual([]);
  });
});
