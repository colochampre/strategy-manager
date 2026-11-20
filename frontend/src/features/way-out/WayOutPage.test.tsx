import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import { heldSubscription, jsonResponse, lock, openPosition, renderAt, resetExchangeScope, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: false } } as const;
const WAY_OUT_LINK = "Close what you hold and delete your account";
const TITLE = "Stop using Strategy Manager";

type Status = "MISSING" | "ACCEPTANCE_OUTDATED" | "COMPLETE";

/** One of the user's own strategies, in the list's shape. */
function ownStrategy(id: string, name: string, enabled: boolean) {
  return {
    id,
    name,
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    subscription: null,
    enabled,
    archived_at: null,
    allowed_pairs: ["ETHUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    created_at: "2026-10-01T10:00:00Z",
    visibility: "PRIVATE",
    share_token: null,
    secret_last4: "x4F2",
    description: null,
    subscribers: 0,
    live_subscribers: 0,
    capital: null,
    stop_loss_pct: "10.00",
  };
}

const RUNNING = ownStrategy("22222222-2222-4222-8222-222222222222", "Breakout", true);
const STOPPED = ownStrategy("33333333-3333-4333-8333-333333333333", "Mean revert", false);

interface Holdings {
  positions?: unknown[];
  seats?: unknown[];
  strategies?: unknown[];
}

/**
 * A user at `status` holding `holdings`. Every write the page sends is recorded and answered as the server would
 * accept it; `/api/me` always answers `status`.
 */
function setup(status: Status, holdings: Holdings = {}, path = "/") {
  const writes: { method: string; url: string; body: unknown }[] = [];
  stubApi(HEALTH, [], undefined, {}, (url, init) => {
    const method = init?.method ?? "GET";
    if (method !== "GET") {
      writes.push({ method, url, body: init?.body === undefined ? undefined : JSON.parse(String(init.body)) });
      if (url.endsWith("/leave")) return Promise.resolve(jsonResponse({ ...heldSubscription(), status: "ENDED" }));
      if (/\/api\/strategies\/[^/]+$/.test(url)) return Promise.resolve(jsonResponse({ ...RUNNING, enabled: false }));
      return undefined;
    }
    if (url.endsWith("/api/me")) {
      return Promise.resolve(
        jsonResponse({
          email: "new@example.com",
          is_admin: false,
          mode: "LIVE",
          dry_run_brake: false,
          profile: null,
          profile_status: status,
          legal_versions: { terms: "t", privacy: "p" },
        }),
      );
    }
    if (url.endsWith("/api/positions/open")) {
      return Promise.resolve(jsonResponse({ as_of: "2026-11-20T18:00:00Z", positions: holdings.positions ?? [], orders: [] }));
    }
    if (url.endsWith("/api/subscriptions/held")) return Promise.resolve(jsonResponse(holdings.seats ?? []));
    if (url.endsWith("/api/strategies")) return Promise.resolve(jsonResponse(holdings.strategies ?? []));
    return undefined;
  });
  renderAt(<AppRoutes />, path);
  return { writes };
}

/** Waits for an element to appear, and fails on the assertion when it never does, not on a lookup. */
async function shown(role: string, name: string, level?: number): Promise<HTMLElement> {
  const query = () => screen.queryByRole(role, level === undefined ? { name } : { name, level });
  await waitFor(() => expect(query()).not.toBeNull());
  return query() as HTMLElement;
}

/** The page's section under the heading `name`: missing, it fails on the assertion, not on a lookup. */
async function section(name: string): Promise<HTMLElement> {
  await shown("heading", TITLE, 1);
  const heading = screen.queryByRole("heading", { level: 2, name });
  expect(heading).not.toBeNull();
  return heading?.closest("section") as HTMLElement;
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

describe("a way out before sign-up", () => {
  it.each<Status>(["MISSING", "ACCEPTANCE_OUTDATED"])(
    "links it from the %s form, and opens it with the navigation still hidden",
    async (status) => {
      setup(status);

      fireEvent.click(await shown("link", WAY_OUT_LINK));

      expect(await shown("heading", TITLE, 1)).toBeInTheDocument();
      expect(screen.queryAllByRole("navigation", { name: "Sections" })).toHaveLength(0);
      // The form, and with it its own link, has given its place to the page.
      expect(screen.queryAllByRole("link", { name: WAY_OUT_LINK })).toHaveLength(0);
    },
  );

  it("shows each thing held with its way out, and the account's deletion", async () => {
    setup(
      "MISSING",
      {
        positions: [openPosition({ strategy_name: "Alpha", markets: ["SOLUSDT"] })],
        seats: [heldSubscription({ strategy_name: "Alpha" })],
        strategies: [RUNNING, STOPPED],
      },
      "/way-out",
    );

    const positions = await section("Open positions");
    expect(await within(positions).findByText("Alpha")).toBeInTheDocument();
    expect(within(positions).getByRole("button", { name: "Close now" })).toBeInTheDocument();

    const seats = await section("Your subscriptions");
    expect(await within(seats).findByText("Alpha")).toBeInTheDocument();
    expect(within(seats).getByRole("button", { name: "Leave" })).toBeInTheDocument();

    const strategies = await section("Your strategies");
    const running = (await within(strategies).findByText("Breakout")).closest("li") as HTMLElement;
    expect(within(running).getByRole("button", { name: "Disable" })).toBeInTheDocument();
    expect(within(running).queryAllByRole("button", { name: "Archive" })).toHaveLength(0);
    const stopped = within(strategies).getByText("Mean revert").closest("li") as HTMLElement;
    expect(within(stopped).getByRole("button", { name: "Archive" })).toBeInTheDocument();
    expect(within(stopped).queryAllByRole("button", { name: "Disable" })).toHaveLength(0);

    const keys = await section("Your exchange keys");
    expect(await within(keys).findByRole("button", { name: "Delete key Bybit" })).toBeInTheDocument();

    expect(screen.getByRole("button", { name: "Delete account" })).toBeInTheDocument();
  });

  it("says when there is nothing to close, leave or stop", async () => {
    setup("MISSING", {}, "/way-out");

    expect(await within(await section("Open positions")).findByText("No open positions.")).toBeInTheDocument();
    expect(await within(await section("Your subscriptions")).findByText("No subscriptions.")).toBeInTheDocument();
    expect(await within(await section("Your strategies")).findByText("No strategies.")).toBeInTheDocument();
  });

  it("leaves out the user's seat on their own strategy, which only archiving ends", async () => {
    setup("MISSING", { seats: [heldSubscription({ strategy_name: "Breakout", authored: true })] }, "/way-out");

    const seats = await section("Your subscriptions");
    expect(await within(seats).findByText("No subscriptions.")).toBeInTheDocument();
    expect(within(seats).queryAllByText("Breakout")).toHaveLength(0);
  });

  it("disables a strategy with a body of exactly enabled false, the one change open before sign-up", async () => {
    const { writes } = setup("MISSING", { strategies: [RUNNING] }, "/way-out");

    fireEvent.click(await within(await section("Your strategies")).findByRole("button", { name: "Disable" }));
    expect(writes).toHaveLength(0);
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Disable" }));

    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]).toEqual({ method: "PATCH", url: expect.stringMatching(/\/api\/strategies\/22222222-2222-4222-8222-222222222222$/), body: { enabled: false } });
  });

  it("leaves a subscription once its dialog is confirmed", async () => {
    const seat = heldSubscription({ strategy_name: "Alpha" });
    const { writes } = setup("MISSING", { seats: [seat] }, "/way-out");

    fireEvent.click(await within(await section("Your subscriptions")).findByRole("button", { name: "Leave" }));
    expect(writes).toHaveLength(0);
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /leave/i }));

    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]?.method).toBe("POST");
    expect(writes[0]?.url).toMatch(new RegExp(`/api/subscriptions/${seat.id}/leave$`));
  });

  it("goes back to the form", async () => {
    setup("MISSING", {}, "/way-out");

    fireEvent.click(await shown("link", "Back to the sign-up"));

    await waitFor(() => expect(screen.queryByLabelText("CUIT or CUIL")).not.toBeNull());
  });

  it("speaks Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    setup("MISSING", {}, "/way-out");

    expect(await shown("heading", "Dejar de usar Strategy Manager", 1)).toBeInTheDocument();
  });
});
