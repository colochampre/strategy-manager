import { screen, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/shared/i18n";
import { AppShell } from "@/shared/layout/AppShell";
import { lock, renderAt, stubApi, unlock } from "@/test/harness";

/** The shell, once it knows the admin is signed in: only then does it offer every section. */
async function renderShell() {
  const view = renderAt(
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<p>page body</p>} />
      </Route>
    </Routes>,
    "/",
  );
  await screen.findByRole("button", { name: "Administration" });
  return view;
}

beforeEach(() => {
  unlock();
  stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

const ICONS = [
  ["link", "Overview", "lucide-layout-dashboard"],
  ["button", "Strategies", "lucide-trending-up"],
  ["link", "Notifications", "lucide-bell"],
  ["button", "Administration", "lucide-shield-check"],
  ["link", /My account/, "lucide-user"],
  ["link", "Sign out", "lucide-log-out"],
] as const;

function sidebar() {
  return screen.getAllByRole("navigation", { name: "Sections" })[0] as HTMLElement;
}

describe("the navigation icons", () => {
  it.each(ICONS)("%s %s carries its own aria-hidden icon, at 16 px, left of the name", async (role, name, iconClass) => {
    await renderShell();

    const item = within(sidebar()).getByRole(role, { name });
    const svgs = Array.from(item.querySelectorAll("svg")).filter((svg) => !svg.classList.contains("lucide-chevron-down"));
    expect(svgs).toHaveLength(1);
    expect(svgs[0]).toHaveAttribute("aria-hidden", "true");
    expect(svgs[0]).toHaveClass(iconClass, "size-4");
    expect(item.firstElementChild).toBe(svgs[0]);
  });

  it("names the Overview in Spanish as the owner's panel de control", async () => {
    await renderShell();

    screen.getByRole("button", { name: /^(Language|Idioma):/ }).click();

    expect(await within(sidebar()).findByRole("link", { name: "Panel de control" })).toHaveAttribute("href", "/");
  });

  it("draws the round flag of the language in use, alone in the button, which names what pressing it does (L.10, L.11)", async () => {
    await renderShell();

    const button = screen.getByRole("button", { name: /^(Language|Idioma):/ });
    const svg = button.querySelector("svg");
    expect(svg).toHaveAttribute("data-flag", "us");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(button.firstElementChild).toBe(svg);
    expect(button).toHaveAccessibleName("Language: English. Switch to Spanish");
  });
});
