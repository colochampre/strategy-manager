import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { storageKeyOf } from "@/features/notifications/lastOpened";
import { NotificationsPage } from "@/features/notifications/NotificationsPage";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import { AppShell } from "@/shared/layout/AppShell";
import { jsonResponse, lock, renderAt, SIGNED_IN_EMAIL, SIGNED_UP, stubApi, unlock } from "@/test/harness";

const STORAGE_KEY = storageKeyOf(SIGNED_IN_EMAIL);
const LONG_AGO = "2026-11-20T00:00:00.000Z";

interface Unseen {
  /** What the server answers for any `since`; a function answers per `since`. */
  kinds: string[] | ((since: string) => string[]);
}

/** A fake server for the shell: who is signed in, and what arrived since the instant the bell asks from. */
function serve(unseen: Unseen) {
  const asked: string[] = [];
  stubApi({ kind: "ok", body: { status: "ok", dry_run: true } }, [], { kind: "ok", body: [] }, {}, (url) => {
    if (url.endsWith("/api/me")) {
      return Promise.resolve(
        jsonResponse({ email: SIGNED_IN_EMAIL, is_admin: false, mode: "LIVE", dry_run_brake: false, ...SIGNED_UP }),
      );
    }
    if (url.includes("/api/notifications/unseen")) {
      const since = new URL(url, "http://x").searchParams.get("since") ?? "";
      asked.push(since);
      return Promise.resolve(jsonResponse({ kinds: typeof unseen.kinds === "function" ? unseen.kinds(since) : unseen.kinds }));
    }
    if (url.includes("/api/notifications")) return Promise.resolve(jsonResponse({ items: [], next_cursor: null }));
    return undefined;
  });
  return asked;
}

function shell(path = "/") {
  renderAt(
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<p>home body</p>} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="settings" element={<p>settings body</p>} />
      </Route>
    </Routes>,
    path,
  );
}

/** The bell in the top row's tools, not the sidebar item of the same page. */
function topBell() {
  const tools = screen.getByRole("group", { name: /^(Tools|Herramientas)$/ });
  return within(tools).getByRole("link", { name: /^Notific/});
}

beforeEach(() => {
  unlock();
  window.localStorage.clear();
});
afterEach(async () => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

describe("the bell of the top row", () => {
  it("sits between the account and the language, and links to the page", async () => {
    serve({ kinds: [] });
    shell();

    const tools = await screen.findByRole("group", { name: "Tools" });
    await waitFor(() => expect(within(tools).getByRole("link", { name: "My account" })).toBeInTheDocument());
    await within(tools).findByRole("link", { name: /^Notifications/ });
    const names = [...tools.querySelectorAll("a, button")].map((element) => element.getAttribute("aria-label"));
    expect(names.indexOf("My account")).toBeGreaterThanOrEqual(0);
    expect(names.indexOf("My account") + 1).toBe(names.findIndex((name) => name?.startsWith("Notifications")));
    expect(names.findIndex((name) => name?.startsWith("Notifications")) + 1).toBe(names.findIndex((name) => name?.startsWith("Language")));
    expect(topBell()).toHaveAttribute("href", "/notifications");
    expect(topBell().querySelector("svg")).toHaveClass("lucide-bell");
  });

  it("with nothing stored, stores now and lights nothing: history alone does not", async () => {
    const before = Date.now();
    const asked = serve({ kinds: (since) => (Date.parse(since) < before ? ["SAFETY"] : []) });
    shell();

    await waitFor(() => expect(asked.length).toBeGreaterThan(0));
    const stored = window.localStorage.getItem(STORAGE_KEY);
    expect(Date.parse(stored ?? "")).toBeGreaterThanOrEqual(before);
    expect(asked[0]).toBe(stored);
    expect(topBell()).toHaveAccessibleName("Notifications");
    expect(screen.queryByTestId("bell-dot")).not.toBeInTheDocument();
  });

  it("keeps no e-mail address in the browser's storage", async () => {
    const asked = serve({ kinds: [] });
    shell();

    await waitFor(() => expect(asked.length).toBeGreaterThan(0));
    const keys = Object.keys(window.localStorage);
    expect(keys.some((key) => key.startsWith("strategy-manager.notifications.last-opened."))).toBe(true);
    expect(keys.filter((key) => key.includes(SIGNED_IN_EMAIL) || key.includes("@"))).toEqual([]);
  });

  it("asks since the stored instant, and lights no dot when nothing is unseen", async () => {
    window.localStorage.setItem(STORAGE_KEY, LONG_AGO);
    const asked = serve({ kinds: [] });
    shell();

    await waitFor(() => expect(asked).toEqual([LONG_AGO]));
    expect(screen.queryByTestId("bell-dot")).not.toBeInTheDocument();
    expect(topBell()).toHaveAccessibleName("Notifications");
  });

  it.each([
    [["SAFETY", "OPERATION"], "SAFETY", "bg-notif-safety"],
    [["DISCREPANCY", "NOTICE"], "DISCREPANCY", "bg-notif-discrepancy"],
    [["NOTICE", "OPERATION"], "NOTICE", "bg-notif-notice"],
    [["OPERATION"], "OPERATION", "bg-notif-operation"],
  ])("with %j unseen, the dot is the colour of the first kind listed", async (kinds, first, tone) => {
    window.localStorage.setItem(STORAGE_KEY, LONG_AGO);
    serve({ kinds });
    shell();

    const dot = await screen.findByTestId("bell-dot");
    expect(dot).toHaveAttribute("data-kind", first);
    expect(dot).toHaveClass(tone);
    expect(topBell()).toHaveAccessibleName("Notifications: there are new ones");
  });

  it.each([
    [["SAFETY"], true],
    [["DISCREPANCY"], true],
    [["NOTICE"], true],
    [["OPERATION", "NOTICE"], true],
    [["OPERATION"], false],
  ])("with %j unseen, the bell shakes: %s, and only when motion is not reduced", async (kinds, shakes) => {
    window.localStorage.setItem(STORAGE_KEY, LONG_AGO);
    serve({ kinds });
    shell();

    await screen.findByTestId("bell-dot");
    const icon = topBell().querySelector("svg");
    if (shakes) expect(icon).toHaveClass("motion-safe:animate-bell-ring");
    else expect(icon?.getAttribute("class")).not.toContain("animate-bell-ring");
  });

  it("reads again every 60 seconds", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.localStorage.setItem(STORAGE_KEY, LONG_AGO);
    const asked = serve({ kinds: [] });
    shell();

    await waitFor(() => expect(asked).toHaveLength(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000);
    });
    await waitFor(() => expect(asked.length).toBeGreaterThanOrEqual(2));
  });

  it("is told apart per user: another person's instant is not read", async () => {
    window.localStorage.setItem(storageKeyOf("someone@else.com"), LONG_AGO);
    const before = Date.now();
    const asked = serve({ kinds: [] });
    shell();

    await waitFor(() => expect(asked).toHaveLength(1));
    expect(Date.parse(asked[0] ?? "")).toBeGreaterThanOrEqual(before);
  });

  it("goes on when the browser refuses its storage: no dot, no crash", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const asked = serve({ kinds: [] });
    shell();

    await waitFor(() => expect(asked.length).toBeGreaterThan(0));
    expect(topBell()).toHaveAccessibleName("Notifications");
  });

  it("goes dark once the page is opened: following it stores the instant and the dot goes", async () => {
    window.localStorage.setItem(STORAGE_KEY, LONG_AGO);
    serve({ kinds: (since) => (since === LONG_AGO ? ["SAFETY"] : []) });
    shell();

    const dot = await screen.findByTestId("bell-dot");
    expect(dot).toBeInTheDocument();
    fireEvent.click(topBell());

    await waitFor(() => expect(screen.queryByTestId("bell-dot")).not.toBeInTheDocument());
    expect(window.localStorage.getItem(STORAGE_KEY)).not.toBe(LONG_AGO);
  });

  it("is named in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    window.localStorage.setItem(STORAGE_KEY, LONG_AGO);
    serve({ kinds: ["NOTICE"] });
    shell();

    await screen.findByTestId("bell-dot");
    expect(topBell()).toHaveAccessibleName("Notificaciones: hay nuevas");
  });

  it("is not drawn for a newcomer who has not signed up", async () => {
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } }, [], undefined, {}, (url) =>
      url.endsWith("/api/me")
        ? Promise.resolve(
            jsonResponse({
              email: SIGNED_IN_EMAIL,
              is_admin: false,
              mode: "LIVE",
              dry_run_brake: false,
              ...SIGNED_UP,
              profile_status: "MISSING",
            }),
          )
        : undefined,
    );
    shell();

    await screen.findByRole("form", { name: en.signUp.label });
    expect(screen.queryByRole("link", { name: /^Notifications/ })).not.toBeInTheDocument();
  });
});
