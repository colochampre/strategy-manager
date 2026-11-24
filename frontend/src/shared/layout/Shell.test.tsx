import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/shared/i18n";
import { AppShell } from "@/shared/layout/AppShell";
import { SIDEBAR_STORAGE_KEY, useSidebarStore } from "@/shared/layout/sidebar-store";
import { jsonResponse, lock, renderAt, resetExchangeScope, SIGNED_UP, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;

type Extra = NonNullable<Parameters<typeof stubApi>[4]>;

function meAs(isAdmin: boolean, displayName: string | null = null): Extra {
  return (url) =>
    url.endsWith("/api/me")
      ? Promise.resolve(
          jsonResponse({
            email: "owner@example.com",
            is_admin: isAdmin,
            mode: "LIVE",
            dry_run_brake: false,
            ...SIGNED_UP,
            display_name: displayName,
          }),
        )
      : undefined;
}

function withBuild(body: string | null, base: Extra = () => undefined): Extra {
  return (url, init) => {
    if (url.endsWith("/build.txt")) {
      return body === null
        ? Promise.resolve(new Response("not found", { status: 404 }))
        : Promise.resolve(new Response(body, { status: 200 }));
    }
    return base(url, init);
  };
}

function renderShell(path = "/") {
  return renderAt(
    <Routes>
      <Route element={<AppShell />}>
        <Route path="*" element={<p>page body</p>} />
      </Route>
    </Routes>,
    path,
  );
}

/** The sidebar's Mi cuenta link, once the sidebar has drawn: the top row's person icon has the same destination. */
async function findSidebar() {
  const [nav] = await screen.findAllByRole("navigation", { name: "Sections" });
  return within(nav as HTMLElement).findByRole("link", { name: /My account/ });
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
  window.localStorage.clear();
  useSidebarStore.setState({ collapsed: false });
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

describe("the mobile drawer", () => {
  beforeEach(() => {
    stubApi(HEALTH, [], undefined, {}, meAs(true));
  });

  it("is closed until the hamburger opens it, and is a dialog with focus inside", async () => {
    renderShell();
    const burger = await screen.findByRole("button", { name: "Open the menu" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(burger);

    const dialog = await screen.findByRole("dialog", { name: "Menu" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    expect(within(dialog).getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/");
  });

  it("closes on Escape and returns focus to the hamburger", async () => {
    renderShell();
    const burger = await screen.findByRole("button", { name: "Open the menu" });
    fireEvent.click(burger);
    await screen.findByRole("dialog", { name: "Menu" });

    fireEvent.keyDown(document.activeElement as HTMLElement, { key: "Escape" });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(burger).toHaveFocus();
  });

  it("closes on a click of the scrim", async () => {
    renderShell();
    fireEvent.click(await screen.findByRole("button", { name: "Open the menu" }));
    await screen.findByRole("dialog", { name: "Menu" });

    fireEvent.click(screen.getByTestId("drawer-scrim"));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes when a link is followed", async () => {
    renderShell();
    fireEvent.click(await screen.findByRole("button", { name: "Open the menu" }));
    const dialog = await screen.findByRole("dialog", { name: "Menu" });

    fireEvent.click(within(dialog).getByRole("link", { name: /My account/ }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("slides in over a fading scrim, and both stop under prefers-reduced-motion", async () => {
    renderShell();
    fireEvent.click(await screen.findByRole("button", { name: "Open the menu" }));

    const dialog = await screen.findByRole("dialog", { name: "Menu" });
    expect(dialog).toHaveClass("animate-drawer-in", "motion-reduce:animate-none");
    expect(screen.getByTestId("drawer-scrim")).toHaveClass("animate-scrim-in", "motion-reduce:animate-none");
  });
});

describe("the sidebar", () => {
  beforeEach(() => {
    stubApi(HEALTH, [], undefined, {}, meAs(true, "Ana"));
  });

  it("opens the Strategies group by default with its three lists, in order", async () => {
    renderShell("/");

    const group = await screen.findByRole("button", { name: "Strategies" });
    expect(group).toHaveAttribute("aria-expanded", "true");
    const nav = screen.getAllByRole("navigation", { name: "Sections" })[0] as HTMLElement;
    const hrefs = within(nav)
      .getAllByRole("link")
      .map((link) => link.getAttribute("href"));
    expect(hrefs.slice(0, 4)).toEqual(["/", "/strategies/authored", "/strategies", "/strategies/explore"]);
  });

  it("toggles a group with aria-expanded, and hides its links while it is closed", async () => {
    renderShell("/");
    const group = await screen.findByRole("button", { name: "Strategies" });
    expect(screen.getByRole("link", { name: "Explore" })).toBeInTheDocument();

    fireEvent.click(group);

    expect(group).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Explore" })).not.toBeInTheDocument();

    fireEvent.click(group);

    expect(group).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Explore" })).toBeInTheDocument();
  });

  it("turns the chevron and animates the group, both instant under prefers-reduced-motion", async () => {
    renderShell("/");
    const group = await screen.findByRole("button", { name: "Strategies" });

    const chevron = group.querySelector("svg.lucide-chevron-down");
    expect(chevron).toHaveClass("rotate-180", "transition-transform", "motion-reduce:transition-none");
    expect(group.parentElement?.querySelector("[data-group-panel]")).toHaveClass(
      "transition-[grid-template-rows]",
      "motion-reduce:transition-none",
    );
  });

  it("marks only the current page with aria-current", async () => {
    renderShell("/strategies/explore");

    expect(await screen.findByRole("link", { name: "Explore" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "My subscriptions" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
  });

  it("offers the admin group, closed, to the admin alone", async () => {
    renderShell("/");

    const admin = await screen.findByRole("button", { name: "Administration" });
    expect(admin).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();

    fireEvent.click(admin);

    expect(screen.getByRole("link", { name: "Users" })).toHaveAttribute("href", "/users");
    expect(screen.getByRole("link", { name: /^Discrepancies/ })).toHaveAttribute("href", "/discrepancies");
  });

  it("opens the admin group when the current page is inside it", async () => {
    renderShell("/users");

    expect(await screen.findByRole("button", { name: "Administration" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Users" })).toHaveAttribute("aria-current", "page");
  });

  it("names Mi cuenta with the user's name, and offers Sign out at the Access logout", async () => {
    renderShell("/");

    const account = await findSidebar();
    expect(account).toHaveAttribute("href", "/settings");
    expect(account).toHaveTextContent("Ana");
    expect(screen.getByRole("link", { name: "Sign out" })).toHaveAttribute("href", "/cdn-cgi/access/logout");
  });

  it("collapses to icons that keep their names, and remembers it in the browser", async () => {
    renderShell("/");
    fireEvent.click(await screen.findByRole("button", { name: "Collapse the sidebar" }));

    expect(await screen.findByRole("button", { name: "Expand the sidebar" })).toBeInTheDocument();
    expect(useSidebarStore.getState().collapsed).toBe(true);
    expect(window.localStorage.getItem(SIDEBAR_STORAGE_KEY)).toContain('"collapsed":true');
    expect(screen.getByRole("link", { name: "Overview" })).toBeInTheDocument();
    expect(await findSidebar()).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign out" })).toBeInTheDocument();
  });

  it("starts collapsed when the browser says it was", async () => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, JSON.stringify({ state: { collapsed: true }, version: 0 }));
    await useSidebarStore.persist.rehydrate();

    renderShell("/");

    expect(await screen.findByRole("button", { name: "Expand the sidebar" })).toBeInTheDocument();
  });

  it("animates its width, and not under prefers-reduced-motion", async () => {
    renderShell("/");

    const nav = (await screen.findAllByRole("navigation", { name: "Sections" }))[0] as HTMLElement;
    expect(nav).toHaveClass("transition-[width]", "motion-reduce:transition-none");
  });

  it("opens the sidebar again when a group is pressed while it is collapsed, so its links stay reachable", async () => {
    useSidebarStore.setState({ collapsed: true });
    renderShell("/");

    fireEvent.click(await screen.findByRole("button", { name: "Strategies" }));

    expect(useSidebarStore.getState().collapsed).toBe(false);
  });
});

describe("the sidebar for someone who is not the admin", () => {
  it("has no administration group at all", async () => {
    stubApi(HEALTH, [], undefined, {}, meAs(false));
    renderShell("/");

    await findSidebar();
    expect(screen.queryByRole("button", { name: "Administration" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
  });
});

describe("the build tag", () => {
  it("names the commit being served", async () => {
    stubApi(HEALTH, [], undefined, {}, withBuild("cf95299\n", meAs(true)));
    renderShell("/");

    expect(await screen.findByText("cf95299")).toBeInTheDocument();
  });

  it("is hidden when build.txt is absent", async () => {
    const api = stubApi(HEALTH, [], undefined, {}, withBuild(null, meAs(true)));
    renderShell("/");

    await waitFor(() => expect(api.mock.calls.some(([url]) => String(url).endsWith("/build.txt"))).toBe(true));
    await findSidebar();
    expect(screen.queryByText(/^build/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("build-tag")).not.toBeInTheDocument();
  });

  it("is hidden when build.txt is not a short commit, as when the SPA fallback answers it", async () => {
    stubApi(HEALTH, [], undefined, {}, withBuild("<!doctype html><html></html>", meAs(true)));
    renderShell("/");

    await findSidebar();
    await waitFor(() => expect(screen.queryByTestId("build-tag")).not.toBeInTheDocument());
  });
});

describe("the top row", () => {
  beforeEach(() => {
    stubApi(HEALTH, [], undefined, {}, meAs(true));
  });

  it("puts, on the right, the mode, the person, the language, in that order, all the same size", async () => {
    renderShell("/settings");

    await screen.findByRole("button", { name: "Mode: Live. Change it" });
    const tools = screen.getByRole("group", { name: "Tools" });
    const items = Array.from(tools.querySelectorAll("button, a"));
    expect(items.map((item) => item.getAttribute("aria-label"))).toEqual([
      "Mode: Live. Change it",
      "My account",
      "Language: English. Switch to Spanish",
    ]);
    const person = within(tools).getByRole("link", { name: "My account" });
    const language = within(tools).getByRole("button", { name: /^Language/ });
    expect(person).toHaveAttribute("href", "/settings");
    expect(person.className).toBe(language.className);
  });

  it.each(["/", "/strategies/authored", "/strategies/5b0c7a52-6f43-4d6e-9c1c-0c2f3f3f2a11"])(
    "draws the exchange buttons on %s, once",
    async (path) => {
      renderShell(path);

      expect(await screen.findAllByRole("navigation", { name: "Exchanges" })).toHaveLength(1);
    },
  );

  it.each(["/settings", "/discrepancies", "/strategies", "/strategies/explore", "/strategies/explore/abc"])(
    "draws no exchange buttons on %s",
    async (path) => {
      renderShell(path);

      await screen.findByRole("group", { name: "Tools" });
      expect(screen.queryByRole("navigation", { name: "Exchanges" })).not.toBeInTheDocument();
    },
  );

  it("lets the exchange buttons scroll sideways", async () => {
    renderShell("/");

    expect(await screen.findByRole("navigation", { name: "Exchanges" })).toHaveClass("overflow-x-auto", "min-w-0");
  });

  it("keeps the language switch, with the flag of the language in use", async () => {
    renderShell("/settings");

    const english = await screen.findByRole("button", { name: "Language: English. Switch to Spanish" });
    expect(english.querySelector("svg")).toHaveAttribute("data-flag", "us");

    fireEvent.click(english);

    const spanish = await screen.findByRole("button", { name: "Idioma: español. Cambiar a inglés" });
    expect(spanish.querySelector("svg")).toHaveAttribute("data-flag", "ar");
    expect(await screen.findByRole("link", { name: "Panel de control" })).toBeInTheDocument();
  });
});

describe("the centred main", () => {
  beforeEach(() => {
    stubApi(HEALTH, [], undefined, {}, meAs(true));
  });

  it("caps every page at 1100 px, centred, with the same padding on every page", async () => {
    const widths = new Set<string>();
    for (const path of ["/", "/settings", "/strategies/explore"]) {
      const view = renderShell(path);
      const main = await screen.findByRole("main");
      const column = main.firstElementChild as HTMLElement;
      expect(column).toHaveClass("mx-auto", "w-full", "max-w-[1100px]");
      widths.add(`${main.className}|${column.className}`);
      view.unmount();
    }
    expect(widths.size).toBe(1);
  });
});

describe("every page keeps a way in", () => {
  it("links each route of the router from the shell, the footer included", async () => {
    stubApi(HEALTH, [], undefined, {}, meAs(true));
    renderShell("/");
    fireEvent.click(await screen.findByRole("button", { name: "Administration" }));

    const hrefs = new Set(screen.getAllByRole("link").map((link) => link.getAttribute("href")));
    for (const path of [
      "/",
      "/strategies",
      "/strategies/explore",
      "/strategies/authored",
      "/discrepancies",
      "/users",
      "/safety-events",
      "/settings",
      "/privacy",
      "/terms",
    ]) {
      expect(hrefs, path).toContain(path);
    }
  });
});

describe("the sign-up step", () => {
  it("shows a newcomer no sidebar, no hamburger and no tools, but the brand and the language", async () => {
    stubApi(HEALTH, [], undefined, {}, (url) =>
      url.endsWith("/api/me")
        ? Promise.resolve(
            jsonResponse({
              email: "new@example.com",
              is_admin: false,
              mode: "SIMULATION",
              dry_run_brake: false,
              profile: null,
              profile_status: "MISSING",
              legal_versions: { terms: "t", privacy: "p" },
              suspended: false,
            }),
          )
        : undefined,
    );
    renderShell("/");

    expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Sections" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open the menu" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "My account" })).not.toBeInTheDocument();
    expect(screen.getByText("Strategy Manager")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Language/ })).toBeInTheDocument();
    // The brand carries the favicon's icon there too (owner, 2026-11-24), as decoration beside the name.
    expect(brandIcons()).toHaveLength(1);
  });

  it("draws the favicon's icon beside the app's name in the sidebar, as decoration (owner, 2026-11-24)", async () => {
    stubApi(HEALTH, [], undefined, {}, meAs(false));
    renderShell("/");

    await screen.findByRole("navigation", { name: "Sections" });
    const icons = brandIcons();
    expect(icons).toHaveLength(1);
    expect(icons[0]).toHaveAttribute("alt", "");
    expect(icons[0]?.parentElement).toHaveTextContent("Strategy Manager");
  });
});

/** The brand's icon: the favicon set's own image, served from the bundle root. */
function brandIcons(): HTMLImageElement[] {
  return Array.from(document.querySelectorAll<HTMLImageElement>('img[src="/android-chrome-192x192.png"]'));
}
