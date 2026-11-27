import { act, screen, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/shared/i18n";
import { AppShell } from "@/shared/layout/AppShell";
import { lock, renderAt, stubApi, unlock } from "@/test/harness";

function sidebar() {
  return screen.getAllByRole("navigation", { name: /Sections|Secciones/ })[0] as HTMLElement;
}

async function renderShell() {
  renderAt(
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<p>page body</p>} />
      </Route>
    </Routes>,
    "/",
  );
  await screen.findByRole("button", { name: /Administration|Administración/ });
}

beforeEach(() => {
  unlock();
  stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

describe("the My trades item of the sidebar (RD.4)", () => {
  it("is the link to /trades right after the Overview, with the arrows icon", async () => {
    await renderShell();

    const links = within(sidebar()).getAllByRole("link");
    const names = links.map((link) => link.textContent);
    expect(names.indexOf("My trades")).toBe(names.indexOf("Overview") + 1);
    const item = within(sidebar()).getByRole("link", { name: "My trades" });
    expect(item).toHaveAttribute("href", "/trades");
    const icon = item.querySelector("svg");
    expect(icon).toHaveClass("lucide-arrow-left-right", "size-4");
    expect(icon).toHaveAttribute("aria-hidden", "true");
  });

  it("is named Mis operaciones in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    await renderShell();

    expect(within(sidebar()).getByRole("link", { name: "Mis operaciones" })).toHaveAttribute("href", "/trades");
  });
});
