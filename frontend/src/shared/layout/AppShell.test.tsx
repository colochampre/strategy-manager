import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Link, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import { AppShell, useWideMain } from "@/shared/layout/AppShell";
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

/** A page that has an aside, as the two strategy pages do: it asks for the wider column. */
function AsidePage() {
  useWideMain();
  return (
    <>
      <p>aside page</p>
      <Link to="/">leave</Link>
    </>
  );
}

/** The sidebar: the one navigation of the shell until the drawer is opened. */
function sidebar() {
  return screen.getByRole("navigation", { name: /^(Sections|Secciones)$/ });
}

beforeEach(() => {
  unlock();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

describe("navigation", () => {
  beforeEach(() => {
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
  });

  it("test_widescreen_shows_the_sidebar_and_narrow_the_hamburger_with_no_bottom_bar", () => {
    renderShell();

    // One navigation: the bottom bar is gone, the drawer is closed.
    const navs = screen.getAllByRole("navigation", { name: "Sections" });
    expect(navs).toHaveLength(1);
    // Hidden by default, flex from `lg`; the hamburger is the reverse.
    expect(navs[0]).toHaveClass("hidden", "lg:flex");
    expect(navs[0]).not.toHaveClass("lg:hidden");
    expect(screen.getByRole("button", { name: "Open the menu" })).toHaveClass("lg:hidden");
  });

  it("lists the pages as router links", () => {
    renderShell();

    for (const [label, href] of [
      ["Overview", "/"],
      ["My strategies", "/strategies/authored"],
      ["My subscriptions", "/strategies"],
      ["Explore", "/strategies/explore"],
      ["Notifications", "/notifications"],
    ] as const) {
      expect(within(sidebar()).getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
    expect(screen.queryByRole("link", { name: "Bookings" })).not.toBeInTheDocument();
  });

  it("marks only the current page active", () => {
    renderShell("/strategies");

    const current = within(sidebar()).getByRole("link", { name: "My subscriptions" });
    expect(current).toHaveAttribute("aria-current", "page");
    expect(current).toHaveClass("text-ink");
    expect(within(sidebar()).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
    expect(within(sidebar()).getByRole("link", { name: "Explore" })).not.toHaveAttribute("aria-current");
  });

  it("moves the active state when a link is followed", async () => {
    renderShell("/");

    fireEvent.click(within(sidebar()).getByRole("link", { name: "My subscriptions" }));

    expect(await screen.findByText("strategies body")).toBeInTheDocument();
    expect(within(sidebar()).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
    expect(within(sidebar()).getByRole("link", { name: "My subscriptions" })).toHaveAttribute("aria-current", "page");
  });

  it("opens every page at its top: main is the scroll container, so a link followed from the bottom of a page lands at the top of the next", async () => {
    renderShell("/strategies");
    const main = screen.getByRole("main");
    main.scrollTop = 500;

    fireEvent.click(within(sidebar()).getByRole("link", { name: "Overview" }));

    expect(await screen.findByText("page body")).toBeInTheDocument();
    expect(main.scrollTop).toBe(0);
  });

  it("keeps the language toggle", () => {
    renderShell();

    fireEvent.click(screen.getByRole("button", { name: /^(Language|Idioma):/ }));
    expect(within(sidebar()).getByRole("link", { name: "Panel de control" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^(Language|Idioma):/ }));
    expect(within(sidebar()).getByRole("link", { name: "Overview" })).toBeInTheDocument();
  });
});

describe("the mode badge in the shell", () => {
  it("names no mode while signed out: a mode belongs to a user", async () => {
    lock();
    stubApi({ kind: "ok", body: { status: "ok", dry_run: false } });
    renderShell();

    expect(await screen.findByText("Mode unknown")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Sign in again" })).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });
});

describe("layout contract", () => {
  beforeEach(() => {
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
  });

  it("fills the viewport height as a flex row of the sidebar and the content area, and scrolls only the content area", () => {
    const { container } = renderShell();

    const root = container.firstElementChild as HTMLElement;
    expect(root).toHaveClass("flex", "h-full");
    expect(root).not.toHaveClass("min-h-full", "h-screen", "overflow-auto", "flex-col");

    const main = screen.getByRole("main");
    expect(main).toHaveClass("flex", "flex-col", "flex-1", "min-h-0", "overflow-auto");
    expect(main.parentElement).toBe(root);
  });

  it("draws no top bar and no bottom bar", () => {
    renderShell();

    expect(screen.queryByRole("banner")).not.toBeInTheDocument();
    expect(screen.getAllByRole("navigation", { name: "Sections" })).toHaveLength(1);
  });

  it("makes the scroll container the containing block of absolutely positioned content, so an sr-only span cannot stretch the document", () => {
    renderShell();

    // Pins the fix, not a measurement: jsdom has no layout. `sr-only` is `position: absolute`; in a scroll
    // container that is not positioned, such a span is laid out against the document and adds a second scrollbar.
    const main = screen.getByRole("main");
    expect(main).toHaveClass("relative", "overflow-auto");
  });

  it("caps the content width at 1100 px inside main and centres it, while main itself stays full width", () => {
    renderShell();

    const main = screen.getByRole("main");
    // `main` keeps the full width so its scrollbar sits at the window edge; the
    // cap is on one inner column that holds every page.
    expect(main.className).not.toMatch(/\bmax-w-/);
    const column = main.firstElementChild as HTMLElement;
    expect(column).toHaveClass("mx-auto", "w-full", "max-w-[1100px]");
    // It fills `main` (so the token gate still fills it) and is a flex column.
    expect(column).toHaveClass("flex", "flex-1", "flex-col");
  });

  it("lets a page with an aside widen the column, and puts the 1100 px cap back when it is left (L26)", async () => {
    renderAt(
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<p>page body</p>} />
          <Route path="aside" element={<AsidePage />} />
        </Route>
      </Routes>,
      "/aside",
    );

    const column = () => screen.getByRole("main").firstElementChild as HTMLElement;
    await screen.findByText("aside page");
    expect(column()).toHaveClass("mx-auto", "w-full", "max-w-[1400px]", "flex-1");
    expect(column()).not.toHaveClass("max-w-[1100px]");

    fireEvent.click(screen.getByRole("link", { name: "leave" }));
    await screen.findByText("page body");
    expect(column()).toHaveClass("max-w-[1100px]");
    expect(column()).not.toHaveClass("max-w-[1400px]");
  });

  it.each(["/strategies/11111111-1111-4111-8111-111111111111", "/strategies/explore/11111111-1111-4111-8111-111111111111"])(
    "gives the strategy page %s, which has an aside, the wider column from its first render (L26)",
    async (path) => {
      stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
      renderAt(<AppRoutes />, path);

      const column = screen.getByRole("main").firstElementChild as HTMLElement;
      await waitFor(() => expect(column).toHaveClass("max-w-[1400px]"));
      expect(column).not.toHaveClass("max-w-[1100px]");
    },
  );

  it.each(["/", "/strategies/authored", "/strategies/explore", "/settings"])(
    "keeps %s, which has no aside, at 1100 px (L26)",
    async (path) => {
      stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
      renderAt(<AppRoutes />, path);

      const column = screen.getByRole("main").firstElementChild as HTMLElement;
      await screen.findByRole("heading", { level: 1 });
      expect(column).toHaveClass("max-w-[1100px]");
      expect(column).not.toHaveClass("max-w-[1400px]");
    },
  );

  it("keeps the 1100 px cap on a page that has no aside", () => {
    renderShell();

    const column = screen.getByRole("main").firstElementChild as HTMLElement;
    expect(column).toHaveClass("max-w-[1100px]");
    expect(column).not.toHaveClass("max-w-[1400px]");
  });

  it("test_the_content_column_grows_with_its_content_so_the_bottom_padding_sits_below_the_last_row", () => {
    renderShell();

    const main = screen.getByRole("main");
    // `main` pads every edge, the bottom one included, at both widths.
    expect(main.className).toMatch(/(^|\s)px-\d/);
    expect(main.className).toMatch(/(^|\s)pb-\d/);
    expect(main.className).toMatch(/(^|\s)lg:pb-\d/);
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
    expect(container.innerHTML).not.toMatch(/min-h-full|h-screen/);
  });

  it("gives every string an English and a Spanish translation", async () => {
    const es = (await import("@/shared/i18n/locales/es.json")).default;
    for (const locale of [en, es]) {
      for (const key of [
        "overview",
        "strategies",
        "authored",
        "subscriptions",
        "explore",
        "admin",
        "account",
        "signOut",
        "collapse",
        "expand",
        "openMenu",
        "closeMenu",
        "menu",
        "home",
        "breadcrumb",
      ] as const) {
        expect(locale.nav[key]).toBeTruthy();
      }
      expect(locale.status.simulation).toBeTruthy();
      expect(locale.status.forced).toBeTruthy();
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

  /** The item sits in the Administration group, closed until it is pressed. */
  async function openAdministration() {
    fireEvent.click(await screen.findByRole("button", { name: /^Administration/ }));
  }

  afterEach(async () => {
    await i18n.changeLanguage("en");
  });

  it("lists the admin's pages in order in the sidebar: the Administration group holds Discrepancies and Users", async () => {
    stubConfirmed({ kind: "ok", body: needing(0) });
    renderShell();

    await openAdministration();
    const links = within(sidebar()).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/",
      "/notifications",
      "/trades",
      "/strategies/authored",
      "/strategies",
      "/strategies/explore",
      "/exchanges",
      "/discrepancies",
      "/users",
      "/settings",
      "/cdn-cgi/access/logout",
    ]);
  });

  it("names the item plainly, and draws no badge, while nothing needs the owner", async () => {
    const fetchMock = stubConfirmed({ kind: "ok", body: needing(0) });
    renderShell();

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/reconciliation/confirmed"))).toBe(true),
    );
    await openAdministration();
    expect(within(sidebar()).getByRole("link", { name: "Discrepancies" })).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it.each([
    [12, "Discrepancies, 12 discrepancies need you"],
    [1, "Discrepancies, 1 discrepancy needs you"],
  ])("gives the item the accessible name of %i, with the number hidden from the tree", async (count, name) => {
    stubConfirmed({ kind: "ok", body: needing(count) });
    renderShell();

    await openAdministration();
    const link = await within(sidebar()).findByRole("link", { name: named(name) });
    expect(within(link).getByText(String(count))).toHaveAttribute("aria-hidden", "true");
  });

  it("keeps what needs the owner in view while the Administration group is closed", async () => {
    stubConfirmed({ kind: "ok", body: needing(12) });
    renderShell();

    const group = await screen.findByRole("button", { name: named("Administration, 12 discrepancies need you") });
    expect(group).toHaveAttribute("aria-expanded", "false");
    expect(within(group).getByText("12")).toHaveClass("bg-loss", "text-ground");
  });

  it("says its name in Spanish, to usted", async () => {
    stubConfirmed({ kind: "ok", body: needing(12) });
    renderShell();
    await openAdministration();
    await within(sidebar()).findByRole("link", { name: named("Discrepancies, 12 discrepancies need you") });

    fireEvent.click(screen.getByRole("button", { name: /^(Language|Idioma):/ }));

    expect(
      await within(sidebar()).findByRole("link", { name: named("Discrepancias, 12 discrepancias requieren su atención") }),
    ).toBeInTheDocument();
  });

  it("draws no badge when dry_run is true, and none while loading or after a first failed read", async () => {
    stubConfirmed({ kind: "ok", body: { ...needing(2), dry_run: true } });
    // The page draws its dry-run sentence only once the read has resolved, so waiting for it proves the badge
    // saw the same answer: a badge that ignored `dry_run` would be drawn by now.
    const dry = renderAt(<AppRoutes />, "/discrepancies");
    expect(await screen.findByText(en.discrepancies.read.dryRun)).toBeInTheDocument();
    expect(screen.queryByText("2")).not.toBeInTheDocument();
    expect(screen.queryByText(/discrepancies need you/)).not.toBeInTheDocument();
    expect(within(sidebar()).getByRole("link", { name: "Discrepancies" })).toBeInTheDocument();
    dry.unmount();

    stubConfirmed({ kind: "pending" });
    const loading = renderShell();
    await openAdministration();
    expect(screen.queryByText("2")).not.toBeInTheDocument();
    expect(within(sidebar()).getByRole("link", { name: "Discrepancies" })).toBeInTheDocument();
    loading.unmount();

    stubConfirmed({ kind: "status", status: 500, body: { detail: "down" } });
    renderShell();
    await openAdministration();
    expect(within(sidebar()).getByRole("link", { name: "Discrepancies" })).toBeInTheDocument();
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
    await openAdministration();
    expect(within(sidebar()).getByRole("link", { name: "Discrepancies" })).toBeInTheDocument();
  });

  it("serves the group's badge and the item's with ONE request", async () => {
    const fetchMock = stubConfirmed({ kind: "ok", body: needing(3) });
    renderShell();

    await openAdministration();
    await within(sidebar()).findByRole("link", { name: named("Discrepancies, 3 discrepancies need you") });
    const requests = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/reconciliation/confirmed"));
    expect(requests).toHaveLength(1);
  });

  it("shows no exchange buttons on /discrepancies, as on Settings, and still shows them on Overview and My strategies (note N7)", async () => {
    stubConfirmed({ kind: "ok", body: needing(2) });
    const discrepancies = renderAt(<AppRoutes />, "/discrepancies");
    expect(await screen.findByRole("heading", { level: 1, name: "Discrepancies" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Exchanges" })).not.toBeInTheDocument();
    discrepancies.unmount();

    for (const path of ["/", "/strategies/authored"]) {
      stubConfirmed({ kind: "ok", body: needing(2) });
      const view = renderAt(<AppRoutes />, path);
      expect(await screen.findAllByRole("navigation", { name: "Exchanges" })).toHaveLength(1);
      view.unmount();
    }
  });

  it("keeps the badge in the line of its label", async () => {
    stubConfirmed({ kind: "ok", body: needing(12) });
    renderShell();
    await openAdministration();

    const link = await within(sidebar()).findByRole("link", { name: named("Discrepancies, 12 discrepancies need you") });

    const badge = within(link).getByText("12");
    expect(badge).not.toHaveClass("absolute");
    expect(link).toHaveClass("justify-between");
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

    expect(await screen.findByRole("heading", { level: 1, name: "My account" })).toBeInTheDocument();
  });
});

describe("privacy in the shell", () => {
  it("shows a newcomer no privacy banner, the sign-up form informs and records the acceptance, and links the policy from every page", async () => {
    window.localStorage.clear();
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
    renderShell("/");

    expect(await screen.findByText("page body")).toBeInTheDocument();
    expect(screen.queryAllByRole("region", { name: "Privacy" })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: "Got it" })).toHaveLength(0);
    expect(screen.getByRole("link", { name: "Privacy policy" })).toHaveAttribute("href", "/privacy");
  });

  it("closes every page with a footer that names the app and links the policy", async () => {
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
    renderShell("/");

    const footer = await screen.findByRole("contentinfo");
    expect(footer).toHaveTextContent(`© ${new Date().getFullYear()} Strategy Manager`);
    expect(within(footer).getByRole("link", { name: "Privacy policy" })).toHaveAttribute("href", "/privacy");
    expect(within(footer).getByRole("link", { name: "Terms of service" })).toHaveAttribute("href", "/terms");
    expect(footer).toHaveClass("border-t");
  });
});

describe("the sign-up step in the shell (public-site LS2)", () => {
  function stubMeAs(profileStatus: "COMPLETE" | "MISSING" | "ACCEPTANCE_OUTDATED") {
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } }, [], undefined, {}, (url, init) =>
      url.endsWith("/api/me") && (init?.method ?? "GET") === "GET"
        ? Promise.resolve(
            new Response(
              JSON.stringify({
                email: "new@example.com",
                is_admin: false,
                mode: "SIMULATION",
                dry_run_brake: false,
                profile: null,
                profile_status: profileStatus,
                legal_versions: { terms: "t", privacy: "p" },
                suspended: false,
              }),
              { status: 200, headers: { "Content-Type": "application/json" } },
            ),
          )
        : undefined,
    );
  }

  it("shows a user who has not signed up the form in place of the page, and still the footer's links", async () => {
    stubMeAs("MISSING");

    renderShell();

    expect(await screen.findByRole("form", { name: en.signUp.label })).toBeInTheDocument();
    expect(screen.queryByText("page body")).not.toBeInTheDocument();
    const footer = screen.getByRole("contentinfo");
    expect(within(footer).getByRole("link", { name: "Terms of service" })).toHaveAttribute("href", "/terms");
  });

  it("shows a signed-up user the sections, the exchange buttons and the mode menu", async () => {
    stubMeAs("COMPLETE");

    renderShell();

    expect(await screen.findByText("page body")).toBeInTheDocument();
    expect(screen.getAllByRole("navigation", { name: "Sections" })).toHaveLength(1);
    expect(await screen.findAllByRole("navigation", { name: en.scope.exchanges })).toHaveLength(1);
    expect(screen.getByText(en.status.simulation)).toBeInTheDocument();
  });

  it.each(["MISSING", "ACCEPTANCE_OUTDATED"] as const)(
    "shows a %s user nothing of the panel to go to or act on, and keeps the brand and the language",
    async (profileStatus) => {
      stubMeAs(profileStatus);

      renderShell();

      expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
      expect(screen.queryAllByRole("navigation", { name: "Sections" })).toHaveLength(0);
      expect(screen.queryAllByRole("navigation", { name: en.scope.exchanges })).toHaveLength(0);
      expect(screen.queryAllByText(en.status.simulation)).toHaveLength(0);
      expect(screen.getByText(en.app.name)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^(Language|Idioma):/ })).toBeInTheDocument();
    },
  );
});
