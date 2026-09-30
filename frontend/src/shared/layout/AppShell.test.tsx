import { fireEvent, screen } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { AppShell } from "@/shared/layout/AppShell";
import { lock, renderAt, stubApi, unlock } from "@/test/harness";

function renderShell(path = "/") {
  return renderAt(
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<p>page body</p>} />
        <Route path="strategies" element={<p>strategies body</p>} />
      </Route>
    </Routes>,
    path,
  );
}

beforeEach(() => {
  unlock();
});
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

describe("navigation", () => {
  beforeEach(() => {
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
  });

  it("test_widescreen_shows_sidenav_narrow_shows_bottomnav", () => {
    renderShell();

    const navs = screen.getAllByRole("navigation", { name: "Sections" });
    expect(navs).toHaveLength(2);
    const side = navs.find((nav) => nav.className.includes("lg:flex"));
    const bottom = navs.find((nav) => nav.className.includes("lg:hidden"));
    // Side rail: hidden by default, flex from `lg`. Bottom bar: the reverse.
    expect(side).toHaveClass("hidden", "lg:flex");
    expect(side).not.toHaveClass("lg:hidden");
    expect(bottom).toHaveClass("lg:hidden");
    expect(bottom).not.toHaveClass("hidden");
    expect(side).not.toBe(bottom);
  });

  it("lists the three sections as router links in both surfaces", () => {
    renderShell();

    for (const [label, href] of [
      ["Overview", "/"],
      ["Strategies", "/strategies"],
      ["Settings", "/settings"],
    ] as const) {
      const links = screen.getAllByRole("link", { name: label });
      expect(links).toHaveLength(2);
      for (const link of links) expect(link).toHaveAttribute("href", href);
    }
    expect(screen.queryByRole("link", { name: "Bookings" })).not.toBeInTheDocument();
  });

  it("marks only the current section active, in both surfaces", () => {
    renderShell("/strategies");

    for (const link of screen.getAllByRole("link", { name: "Strategies" })) {
      expect(link).toHaveAttribute("aria-current", "page");
      expect(link).toHaveClass("text-ink");
    }
    for (const link of screen.getAllByRole("link", { name: "Overview" })) {
      expect(link).not.toHaveAttribute("aria-current");
    }
  });

  it("moves the active state when a link is followed", () => {
    renderShell("/");

    fireEvent.click(screen.getAllByRole("link", { name: "Strategies" })[0] as HTMLElement);

    expect(screen.getByText("strategies body")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Overview" })[0]).not.toHaveAttribute("aria-current");
  });

  it("keeps the language toggle", () => {
    renderShell();

    fireEvent.click(screen.getByRole("button", { name: /^(es|en)$/i }));
    expect(screen.getAllByRole("link", { name: "Resumen" })).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: /^(es|en)$/i }));
    expect(screen.getAllByRole("link", { name: "Overview" })).toHaveLength(2);
  });
});

describe("DryRunBadge", () => {
  it("test_dry_run_badge_reads_health_dry_run_field", async () => {
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
    renderShell();

    expect(await screen.findByText("Dry run")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("reads /health without the admin token and without the /api prefix", async () => {
    const fetchMock = stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
    renderShell();

    await screen.findByText("Dry run");
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/health"));
    expect(String(call?.[0])).toBe("/health");
    expect(new Headers(call?.[1]?.headers).has("Authorization")).toBe(false);
  });

  it("says Live, in the loss colour, when the server reports dry_run false", async () => {
    stubApi({ kind: "ok", body: { status: "ok", dry_run: false } });
    renderShell();

    const badge = await screen.findByText("Live");
    expect(badge).toHaveClass("text-loss");
    expect(screen.queryByText("Dry run")).not.toBeInTheDocument();
  });

  it("shows a neutral checking state while /health is loading, never Live", () => {
    stubApi({ kind: "pending" });
    renderShell();

    const badge = screen.getByText("Checking mode");
    expect(badge).toHaveClass("text-ink-3");
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByText("Dry run")).not.toBeInTheDocument();
  });

  it("shows Mode unknown, never Live, when /health fails on the network", async () => {
    stubApi({ kind: "network-error" });
    renderShell();

    const badge = await screen.findByText("Mode unknown");
    expect(badge).toHaveClass("text-ink-3");
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByText("Dry run")).not.toBeInTheDocument();
  });

  it("shows Mode unknown on a 500", async () => {
    stubApi({ kind: "status", status: 500, body: { status: "ok", dry_run: false } });
    renderShell();

    expect(await screen.findByText("Mode unknown")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("shows Mode unknown on a body without a boolean dry_run", async () => {
    for (const body of [{ status: "ok" }, { status: "ok", dry_run: "false" }, null]) {
      stubApi({ kind: "ok", body });
      const view = renderShell();
      expect(await screen.findByText("Mode unknown")).toBeInTheDocument();
      expect(screen.queryByText("Live")).not.toBeInTheDocument();
      view.unmount();
    }
  });

  it("is visible while the token gate is locked, because /health needs no token", async () => {
    lock();
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
    renderShell();

    expect(await screen.findByText("Dry run")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unlock" })).toBeInTheDocument();
  });
});

describe("layout contract", () => {
  beforeEach(() => {
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
  });

  it("fills the viewport height as a flex column and scrolls only the content area", () => {
    const { container } = renderShell();

    const root = container.firstElementChild as HTMLElement;
    expect(root).toHaveClass("flex", "h-full", "flex-col");
    expect(root).not.toHaveClass("min-h-full", "h-screen", "overflow-auto");

    const main = screen.getByRole("main");
    expect(main).toHaveClass("flex", "flex-col", "flex-1", "min-h-0", "overflow-auto");
    expect(main.parentElement).toHaveClass("min-h-0", "flex-1");
  });

  it("keeps the one-viewport contract with the exchange tabs row in the header", async () => {
    const { container } = renderShell();

    const tabs = await screen.findAllByRole("navigation", { name: "Exchanges" });
    const header = screen.getByRole("banner");
    // The header is a non-shrinking, non-overlaying row of the column, and the
    // tabs sit inside it, so they add height to the header and take it from
    // `main`, never from the page.
    expect(header).toHaveClass("shrink-0");
    expect(header).not.toHaveClass("fixed", "sticky", "absolute");
    expect(header.parentElement).toBe(container.firstElementChild);
    for (const bar of tabs) {
      expect(header).toContainElement(bar);
      expect(bar).toHaveClass("overflow-x-auto", "min-w-0");
    }
    expect(screen.getByRole("main")).toHaveClass("flex-1", "min-h-0", "overflow-auto");
    expect(container.innerHTML).not.toMatch(/min-h-full|h-screen/);
  });

  it("does not reserve bottom-bar space with padding hacks that can overflow", () => {
    const { container } = renderShell();

    expect(screen.getByRole("main").className).not.toMatch(/\bpb-20\b/);
    // The bottom bar is a sibling in the column, not a fixed overlay.
    for (const nav of screen.getAllByRole("navigation", { name: "Sections" })) {
      expect(nav).not.toHaveClass("fixed");
    }
    expect(container.innerHTML).not.toMatch(/min-h-full|h-screen/);
  });

  it("gives every string an English and a Spanish translation", () => {
    for (const locale of [en, es]) {
      for (const key of ["overview", "strategies", "settings"] as const) {
        expect(locale.nav[key]).toBeTruthy();
      }
      expect(locale.status.dryRun).toBeTruthy();
      expect(locale.status.live).toBeTruthy();
      expect(locale.status.checking).toBeTruthy();
      expect(locale.status.unknown).toBeTruthy();
      expect(locale.notFound.title).toBeTruthy();
      expect(locale.notFound.back).toBeTruthy();
    }
  });
});

describe("pages", () => {
  it("renders the routed shell from the real route map", async () => {
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
    renderAt(<AppRoutes />, "/settings");

    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
  });
});
