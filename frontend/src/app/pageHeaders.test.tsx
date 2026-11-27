import { act, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { lock, renderAt, resetExchangeScope, stubApi, unlock } from "@/test/harness";

/** S2: every page opens with a breadcrumb, a title and a subtitle, in the same header. */
const PAGES: ReadonlyArray<{ path: string; crumbs: string[]; title: string; subtitle: string }> = [
  { path: "/", crumbs: ["Overview"], title: "Overview", subtitle: en.pageHeader.overview },
  {
    path: "/strategies",
    crumbs: ["Strategies", "My subscriptions"],
    title: "My subscriptions",
    subtitle: en.pageHeader.subscriptions,
  },
  { path: "/strategies/explore", crumbs: ["Strategies", "Explore"], title: "Explore", subtitle: en.pageHeader.explore },
  {
    path: "/strategies/authored",
    crumbs: ["Strategies", "My strategies"],
    title: "My strategies",
    subtitle: en.pageHeader.authored,
  },
  { path: "/trades", crumbs: ["My trades"], title: "My trades", subtitle: en.pageHeader.trades },
  { path: "/settings", crumbs: ["My account"], title: "My account", subtitle: en.pageHeader.account },
  { path: "/exchanges", crumbs: ["Link exchange"], title: "Link exchange", subtitle: en.pageHeader.exchanges },
  { path: "/notifications", crumbs: ["Notifications"], title: "Notifications", subtitle: en.notifications.intro },
  { path: "/users", crumbs: ["Administration", "Users"], title: "Users", subtitle: en.pageHeader.users },
  { path: "/no/such/page", crumbs: ["Page not found"], title: "Page not found", subtitle: en.pageHeader.notFound },
];

beforeEach(() => {
  unlock();
  resetExchangeScope();
  stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

describe("the page header", () => {
  it.each(PAGES)("opens $path with its breadcrumb, title and subtitle", async ({ path, crumbs, title, subtitle }) => {
    renderAt(<AppRoutes />, path);

    expect(await screen.findByRole("heading", { level: 1, name: title })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    const trail = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(trail).getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
    const items = within(trail)
      .getAllByRole("listitem")
      .map((item) => item.textContent ?? "")
      .filter((text) => text !== "");
    expect(items).toEqual(crumbs);
    expect(screen.getByText(subtitle)).toBeInTheDocument();
  });

  it("opens Discrepancies with its breadcrumb and its title, and the lede once the read has answered", async () => {
    renderAt(<AppRoutes />, "/discrepancies");

    expect(await screen.findByRole("heading", { level: 1, name: "Discrepancies" })).toBeInTheDocument();
    const trail = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(trail).getByText("Administration")).toBeInTheDocument();
    expect(await screen.findByText(en.discrepancies.lede)).toBeInTheDocument();
  });

  it("is the same header in Spanish, to usted", async () => {
    await act(() => i18n.changeLanguage("es"));
    renderAt(<AppRoutes />, "/strategies/explore");

    expect(await screen.findByRole("heading", { level: 1, name: "Explorar" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Ruta de navegación" })).toBeInTheDocument();
    expect(screen.getByText(es.pageHeader.explore)).toBeInTheDocument();
  });

  it("gives every page the same header markup, so the title never jumps", async () => {
    const shapes = new Set<string>();
    for (const { path, title } of PAGES) {
      const view = renderAt(<AppRoutes />, path);
      const heading = await screen.findByRole("heading", { level: 1, name: title });
      shapes.add(`${heading.className}|${heading.closest("header")?.className}`);
      view.unmount();
    }
    expect(shapes.size).toBe(1);
  });
});
