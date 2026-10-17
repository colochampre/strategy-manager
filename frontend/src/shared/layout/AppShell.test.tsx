import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { AppShell } from "@/shared/layout/AppShell";
import { booking, confirmedBody, discrepancy, lock, pool, renderAt, stubApi, unlock } from "@/test/harness";
import type { ConfirmedStub } from "@/test/harness";

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

  it("says Live, in the gain colour, when the server reports dry_run false", async () => {
    stubApi({ kind: "ok", body: { status: "ok", dry_run: false } });
    renderShell();

    const badge = await screen.findByText("Live");
    expect(badge).toHaveClass("text-gain");
    expect(badge).toHaveClass("border-gain");
    expect(badge).not.toHaveClass("text-loss");
    expect(badge).not.toHaveClass("border-loss");
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

  it("makes the scroll container the containing block of absolutely positioned content, so an sr-only span cannot stretch the document", () => {
    renderShell();

    // Pins the fix, not a measurement: jsdom has no layout. `sr-only` is `position: absolute`; in a scroll
    // container that is not positioned, such a span is laid out against the document and adds a second scrollbar.
    const main = screen.getByRole("main");
    expect(main).toHaveClass("relative", "overflow-auto");
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

  it("caps the content width inside main and centres it, while main itself stays full width", () => {
    renderShell();

    const main = screen.getByRole("main");
    // `main` keeps the full width so its scrollbar sits at the window edge; the
    // cap is on one inner column that holds every page (decision 38).
    expect(main.className).not.toMatch(/\bmax-w-/);
    const column = main.firstElementChild as HTMLElement;
    expect(column).toHaveClass("mx-auto", "w-full", "max-w-[90rem]");
    // It fills `main` (so the token gate still fills it) and is a flex column.
    expect(column).toHaveClass("flex", "flex-1", "flex-col");
  });

  it("test_the_content_column_grows_with_its_content_so_the_bottom_padding_sits_below_the_last_row", () => {
    renderShell();

    const main = screen.getByRole("main");
    // `main` pads every edge, the bottom one included, at both widths.
    expect(main.className).toMatch(/(^|\s)p-\d/);
    expect(main.className).toMatch(/(^|\s)lg:py-\d/);
    // The padding only helps if the column is as tall as its content. With
    // `min-h-0` the column is capped at the space `main` leaves, the content
    // overflows it, and the last row ends flush with the scroll edge, because
    // the padding sits under the capped column, not under the content (7p.3).
    const column = main.firstElementChild as HTMLElement;
    expect(column).not.toHaveClass("min-h-0");
    // `main` is the one scroller and still may shrink below its content.
    expect(main).toHaveClass("min-h-0", "overflow-auto");
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

describe("the Discrepancies item and its badge", () => {
  const HEALTH = { kind: "ok", body: { status: "ok", dry_run: false } } as const;

  function stubConfirmed(confirmed: ConfirmedStub) {
    return stubApi(HEALTH, [], undefined, {}, undefined, {}, undefined, undefined, confirmed);
  }

  function needing(count: number) {
    return confirmedBody({ needs_owner: Array.from({ length: count }, () => discrepancy()) });
  }

  /**
   * The item's accessible name is its label, then the badge's words after a comma. The markup keeps them in two
   * elements, which the name computation joins with a space: "Discrepancies , 12 ...". The space is dropped.
   */
  const named = (expected: string) => (name: string) => name.replace(/\s+,/g, ",") === expected;

  afterEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("lists four sections in order, in the side navigation and in the bottom bar", () => {
    stubConfirmed({ kind: "ok", body: needing(0) });
    renderShell();

    const navs = screen.getAllByRole("navigation", { name: "Sections" });
    expect(navs).toHaveLength(2);
    for (const nav of navs) {
      const links = within(nav).getAllByRole("link");
      expect(links.map((link) => link.textContent)).toEqual(["Overview", "Strategies", "Discrepancies", "Settings"]);
      expect(links.map((link) => link.getAttribute("href"))).toEqual(["/", "/strategies", "/discrepancies", "/settings"]);
    }
  });

  it("names the item plainly, and draws no badge, while nothing needs the owner", async () => {
    const fetchMock = stubConfirmed({ kind: "ok", body: needing(0) });
    renderShell();

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/reconciliation/confirmed"))).toBe(true),
    );
    expect(screen.getAllByRole("link", { name: "Discrepancies" })).toHaveLength(2);
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it.each([
    [12, "Discrepancies, 12 discrepancies need you"],
    [1, "Discrepancies, 1 discrepancy needs you"],
  ])("gives the item the accessible name of %i in both surfaces, with the number hidden from the tree", async (count, name) => {
    stubConfirmed({ kind: "ok", body: needing(count) });
    renderShell();

    const links = await screen.findAllByRole("link", { name: named(name) });
    expect(links).toHaveLength(2);
    for (const link of links) {
      expect(within(link).getByText(String(count))).toHaveAttribute("aria-hidden", "true");
    }
  });

  it("draws the same badge in both surfaces", async () => {
    stubConfirmed({ kind: "ok", body: needing(12) });
    renderShell();

    const [side, bottom] = screen.getAllByRole("navigation", { name: "Sections" }) as [HTMLElement, HTMLElement];
    const sideBadge = await within(side).findByText("12");
    const bottomBadge = await within(bottom).findByText("12");
    expect(sideBadge).toHaveClass("bg-loss", "text-ground");
    expect(bottomBadge).toHaveClass("bg-loss", "text-ground");
    expect(sideBadge.tagName).toBe(bottomBadge.tagName);
    expect(within(side).getByText(/12 discrepancies need you/).textContent).toBe(
      within(bottom).getByText(/12 discrepancies need you/).textContent,
    );
  });

  it("says its name in Spanish, to usted", async () => {
    stubConfirmed({ kind: "ok", body: needing(12) });
    renderShell();
    await screen.findAllByRole("link", { name: named("Discrepancies, 12 discrepancies need you") });

    fireEvent.click(screen.getByRole("button", { name: /^(es|en)$/i }));

    expect(
      await screen.findAllByRole("link", { name: named("Discrepancias, 12 discrepancias requieren su atención") }),
    ).toHaveLength(2);
  });

  it("draws no badge when dry_run is true, and none while loading or after a first failed read", async () => {
    stubConfirmed({ kind: "ok", body: { ...needing(2), dry_run: true } });
    const dry = renderShell();
    await screen.findAllByRole("link", { name: "Discrepancies" });
    await waitFor(() => expect(screen.queryByText("2")).not.toBeInTheDocument());
    dry.unmount();

    stubConfirmed({ kind: "pending" });
    const loading = renderShell();
    expect(screen.queryByText("2")).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Discrepancies" })).toHaveLength(2);
    loading.unmount();

    stubConfirmed({ kind: "status", status: 500, body: { detail: "down" } });
    renderShell();
    await screen.findAllByRole("link", { name: "Discrepancies" });
    expect(screen.getAllByRole("link", { name: "Discrepancies" })).toHaveLength(2);
  });

  it("draws no badge for an item being booked or for bookings", async () => {
    const fetchMock = stubConfirmed({
      kind: "ok",
      body: confirmedBody({ being_booked: [discrepancy({ reason: null })], booked: [booking(), booking()] }),
    });
    renderShell();

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/reconciliation/confirmed"))).toBe(true),
    );
    expect(screen.getAllByRole("link", { name: "Discrepancies" })).toHaveLength(2);
  });

  it("serves the side navigation and the bottom bar with ONE request", async () => {
    const fetchMock = stubConfirmed({ kind: "ok", body: needing(3) });
    renderShell();

    await screen.findAllByRole("link", { name: named("Discrepancies, 3 discrepancies need you") });
    const requests = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/reconciliation/confirmed"));
    expect(requests).toHaveLength(1);
  });

  it("gives the bottom bar four equal cells whose labels sit level whether or not a badge is drawn", async () => {
    stubConfirmed({ kind: "ok", body: needing(12) });
    renderShell();
    const bottom = screen.getAllByRole("navigation", { name: "Sections" })[1] as HTMLElement;
    await within(bottom).findByText("12");

    const cells = within(bottom).getAllByRole("link");
    expect(cells).toHaveLength(4);
    for (const cell of cells) {
      expect(cell).toHaveClass("flex-1", "min-w-0", "items-end", "pb-2", "relative");
      expect(cell).not.toHaveClass("items-center");
    }
    // The badge sits in the corner of its cell, out of the label's line.
    expect(within(bottom).getByText("12")).toHaveClass("absolute", "top-1", "right-1");
  });

  it("keeps the side rail's badge in the line of its label", async () => {
    stubConfirmed({ kind: "ok", body: needing(12) });
    renderShell();
    const side = screen.getAllByRole("navigation", { name: "Sections" })[0] as HTMLElement;

    const badge = await within(side).findByText("12");

    expect(badge).not.toHaveClass("absolute");
    expect(within(side).getByRole("link", { name: /^Discrepancies/ })).toHaveClass("justify-between");
  });
});

describe("pages", () => {
  it("test_an_overview_with_several_pools_has_no_height_cap_between_its_content_and_main", async () => {
    const pools = [pool("bybit", "usdt-m", "USDT"), pool("bybit", "coin-m", "BTC"), pool("bybit", "coin-m", "ETH")];
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } }, [], { kind: "ok", body: pools });
    renderAt(<AppRoutes />, "/");

    const main = screen.getByRole("main");
    const title = await screen.findByRole("heading", { level: 1, name: "Overview" });
    expect(await screen.findAllByRole("region", { name: /USDT|BTC|ETH/ })).not.toHaveLength(0);
    // Every ancestor up to `main` must be as tall as its content, or the last
    // panel overflows it and ends flush with the scroll edge (7p.3).
    let node = title.parentElement;
    let depth = 0;
    while (node !== null && node !== main) {
      expect(node.className).not.toMatch(/(^|\s)(min-h-0|overflow-\S+|max-h-\S+|h-\S+)(\s|$)/);
      node = node.parentElement;
      depth += 1;
    }
    expect(node).toBe(main);
    expect(depth).toBeGreaterThan(1);
  });

  it("renders the routed shell from the real route map", async () => {
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
    renderAt(<AppRoutes />, "/settings");

    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
  });
});
