import { fireEvent, screen, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/shared/i18n";
import { AppShell } from "@/shared/layout/AppShell";
import { lock, renderAt, stubApi, unlock } from "@/test/harness";

function renderShell() {
  return renderAt(
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<p>page body</p>} />
      </Route>
    </Routes>,
    "/",
  );
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
  ["Overview", "lucide-layout-dashboard"],
  ["Strategies", "lucide-chart-candlestick"],
  ["Discrepancies", "lucide-scale"],
  ["Settings", "lucide-settings"],
] as const;

function navs() {
  const all = screen.getAllByRole("navigation", { name: "Sections" });
  return {
    side: all.find((nav) => nav.className.includes("lg:flex"))!,
    bottom: all.find((nav) => nav.className.includes("lg:hidden"))!,
  };
}

describe("the navigation icons", () => {
  it.each(ICONS)("%s carries its own aria-hidden icon in both navigations", (label, iconClass) => {
    renderShell();
    const { side, bottom } = navs();

    for (const nav of [side, bottom]) {
      const link = within(nav).getByRole("link", { name: label });
      const svgs = link.querySelectorAll("svg");
      expect(svgs).toHaveLength(1);
      expect(svgs[0]).toHaveAttribute("aria-hidden", "true");
      expect(svgs[0]).toHaveClass(iconClass);
    }
  });

  it("draws the bottom bar's icon at 20 px", () => {
    renderShell();

    for (const [label] of ICONS) {
      const svg = within(navs().bottom).getByRole("link", { name: label }).querySelector("svg");
      expect(svg).toHaveClass("size-5");
    }
  });

  it("draws the side rail's icon at 16 px, left of the name", () => {
    renderShell();

    const link = within(navs().side).getByRole("link", { name: "Overview" });
    expect(link.querySelector("svg")).toHaveClass("size-4");
    const svg = link.querySelector("svg");
    expect(link.firstElementChild).toBe(svg?.parentElement);
    expect(svg?.parentElement?.firstElementChild).toBe(svg);
    expect(svg?.parentElement).toHaveTextContent("Overview");
  });

  it("shows no visible label in the bottom bar: the name is sr-only text and the title", () => {
    renderShell();

    for (const [label] of ICONS) {
      const link = within(navs().bottom).getByRole("link", { name: label });
      expect(link).toHaveAttribute("title", label);
      const text = within(link).getByText(label);
      expect(text).toHaveClass("sr-only");
    }
  });

  it("titles the bottom bar's links in Spanish too", async () => {
    renderShell();
    const { bottom } = navs();

    fireEvent.click(screen.getByRole("button", { name: /^(es|en)$/i }));

    const link = within(bottom).getByRole("link", { name: "Resumen" });
    expect(link).toHaveAttribute("title", "Resumen");
  });

  it("draws the language symbol left of the switch's text, without changing its name", () => {
    renderShell();

    const button = screen.getByRole("button", { name: /^(es|en)$/i });
    const svg = button.querySelector("svg");
    expect(svg).toHaveClass("lucide-languages");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(button.firstElementChild).toBe(svg);
    expect(button).toHaveAccessibleName("es");
  });
});
