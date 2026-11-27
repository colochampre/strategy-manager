import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { storageKeyOf } from "@/features/notifications/lastOpened";
import { NotificationsPage } from "@/features/notifications/NotificationsPage";
import type { NotificationItem } from "@/shared/api/notifications";
import i18n from "@/shared/i18n";
import { jsonResponse, lock, renderAt, SIGNED_IN_EMAIL, SIGNED_UP, stubApi, unlock } from "@/test/harness";

const HOUR = 3600e3;
const NOW = Date.now();
const TODAY = new Date(NOW).toISOString();
/** An hour before this UTC day began, so it is Yesterday whatever the hour the test runs at. */
const YESTERDAY = new Date(Math.floor(NOW / (24 * HOUR)) * 24 * HOUR - HOUR).toISOString();

let sequence = 0;

/** An opening of "Alpha", live, on Bybit; the overrides replace any field. */
function item(overrides: Partial<NotificationItem> = {}): NotificationItem {
  sequence += 1;
  return {
    id: `opened:${sequence}`,
    kind: "OPERATION",
    event: "OPENED",
    occurred_at: new Date(NOW - sequence * 60e3).toISOString(),
    reason: null,
    strategy_id: "s1",
    strategy_name: "Alpha",
    exchange: "bybit",
    venue: "usdt-m",
    pair: "SOLUSDT",
    side: "LONG",
    rehearsal: false,
    currency: "USDT",
    entry_price: "100.5",
    exit_price: null,
    pnl: null,
    leverage: "3",
    close_cause: null,
    detail: {},
    ...overrides,
  };
}

function closed(cause: string, overrides: Partial<NotificationItem> = {}): NotificationItem {
  return item({
    event: "CLOSED",
    close_cause: cause,
    exit_price: "110",
    pnl: "5.5",
    kind: cause === "SIGNAL" || cause === "MANUAL_CLOSE" ? "OPERATION" : "SAFETY",
    ...overrides,
  });
}

interface Asked {
  kind: string | null;
  cursor: string | null;
  limit: string | null;
}

/** A fake server: the items newest first, cut by `limit`, `kind` and an offset cursor; every feed read is recorded. */
function serve(items: NotificationItem[], options: { admin?: boolean; failFeed?: boolean; pending?: boolean } = {}) {
  const asked: Asked[] = [];
  stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) => {
    if (url.endsWith("/api/me")) {
      return Promise.resolve(
        jsonResponse({
          email: SIGNED_IN_EMAIL,
          is_admin: options.admin ?? true,
          mode: "LIVE",
          dry_run_brake: false,
          ...SIGNED_UP,
        }),
      );
    }
    if (url.includes("/api/notifications/unseen")) return Promise.resolve(jsonResponse({ kinds: [] }));
    if (!url.includes("/api/notifications")) return undefined;
    const params = new URL(url, "http://x").searchParams;
    asked.push({ kind: params.get("kind"), cursor: params.get("cursor"), limit: params.get("limit") });
    if (options.pending) return new Promise<Response>(() => undefined);
    if (options.failFeed) return Promise.resolve(jsonResponse({ nope: true }));
    const kind = params.get("kind");
    const matching = items.filter((entry) => kind === null || entry.kind === kind);
    const start = Number(params.get("cursor") ?? "0");
    const limit = Number(params.get("limit") ?? "30");
    const next = start + limit;
    return Promise.resolve(
      jsonResponse({ items: matching.slice(start, next), next_cursor: next < matching.length ? String(next) : null }),
    );
  });
  return asked;
}

function open() {
  renderAt(<NotificationsPage />, "/notifications");
}

function rows() {
  return screen.getAllByTestId("notification");
}

beforeEach(unlock);
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

describe("NotificationsPage", () => {
  it("opens with its breadcrumb, title and subtitle", async () => {
    serve([]);
    open();

    expect(await screen.findByRole("heading", { level: 1, name: "Notifications" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent("Notifications");
    expect(screen.getByText(/newest first/)).toBeInTheDocument();
  });

  it.each([
    [
      "an opening",
      item({ id: "opened:x", entry_price: "96420.5", leverage: "3", pair: "BTCUSDT", exchange: "binance" }),
      "Opening in Alpha",
      "Long on BTCUSDT on Binance, entry at 96420.5 USDT, leverage 3x.",
      "Operation",
      "OPERATION",
    ],
    [
      "a close by the signal",
      closed("SIGNAL", { pnl: "27.4" }),
      "Close in Alpha",
      "Long on SOLUSDT on Bybit closed at 110 USDT. Result +27.40 USDT.",
      "Operation",
      "OPERATION",
    ],
    [
      "a close by the stop",
      closed("STOP_FIRED", { pnl: "-31.8", exit_price: "171.55" }),
      "Stop fired in Alpha",
      "Long on SOLUSDT on Bybit closed by the stop at 171.55 USDT. Result -31.80 USDT.",
      "Safety",
      "SAFETY",
    ],
    [
      "a safety close after a failed stop",
      closed("STOP_FAILED_CLOSED"),
      "Safety close in Alpha",
      "closed for safety",
      "Safety",
      "SAFETY",
    ],
    [
      "a close when the strategy stopped",
      closed("STRATEGY_STOPPED_CLOSED"),
      "Close in Alpha, which stopped",
      "closed because the strategy was disabled",
      "Safety",
      "SAFETY",
    ],
    [
      "an opening refused by the leverage cap",
      item({
        kind: "SAFETY",
        event: "OPENING_REFUSED",
        reason: "OPENING_REFUSED_LEVERAGE_CAP",
        detail: { requested_leverage: "10", max_leverage: "6", stop_loss_pct: "15" },
      }),
      "Opening refused in Alpha",
      "The leverage you chose (10x) is above the 6x that the strategy's stop allows. No capital was reserved.",
      "Safety",
      "SAFETY",
    ],
    [
      "an opening refused for a suspended account",
      item({ kind: "SAFETY", event: "OPENING_REFUSED", reason: "OPENING_REFUSED_ACCOUNT_SUSPENDED" }),
      "Opening refused in Alpha",
      "Your account is suspended. No capital was reserved.",
      "Safety",
      "SAFETY",
    ],
    [
      "an opening refused for a suspended author",
      item({ kind: "SAFETY", event: "OPENING_REFUSED", reason: "OPENING_REFUSED_AUTHOR_SUSPENDED" }),
      "Opening refused in Alpha",
      "The strategy's author is suspended. No capital was reserved.",
      "Safety",
      "SAFETY",
    ],
    [
      "a read-only key",
      item({ kind: "NOTICE", event: "OPENING_REFUSED", reason: "EXCHANGE_KEY_READ_ONLY" }),
      "Opening refused in Alpha",
      "Your Bybit key is read-only, so it cannot trade live. No capital was reserved.",
      "Notice",
      "NOTICE",
    ],
    [
      "no key",
      item({ kind: "NOTICE", event: "OPENING_REFUSED", reason: "EXCHANGE_HAS_NO_KEY" }),
      "Opening refused in Alpha",
      "You have no key for Bybit. No capital was reserved.",
      "Notice",
      "NOTICE",
    ],
    [
      "margin that is not isolated",
      item({ kind: "NOTICE", event: "OPENING_REFUSED", reason: "MARGIN_NOT_ISOLATED" }),
      "Opening refused in Alpha",
      "Your Bybit account is not on isolated margin. No capital was reserved.",
      "Notice",
      "NOTICE",
    ],
    [
      "a leverage that conflicts",
      item({ kind: "NOTICE", event: "OPENING_REFUSED", reason: "LEVERAGE_CONFLICT" }),
      "Opening refused in Alpha",
      "You already hold SOLUSDT at another leverage",
      "Notice",
      "NOTICE",
    ],
    [
      "a leverage the exchange did not apply",
      item({ kind: "NOTICE", event: "OPENING_REFUSED", reason: "LEVERAGE_NOT_APPLIED" }),
      "Opening refused in Alpha",
      "did not apply the leverage",
      "Notice",
      "NOTICE",
    ],
    [
      "a discrepancy",
      item({
        kind: "DISCREPANCY",
        event: "DISCREPANCY",
        reason: "NO_MATCHING_ALLOCATION",
        strategy_id: null,
        strategy_name: null,
        pair: "STXUSDT",
        exchange: "binance",
        side: null,
      }),
      "Position without an allocation on Binance",
      "The STXUSDT position on the exchange matches no allocation. It needs your decision.",
      "Discrepancy",
      "DISCREPANCY",
    ],
  ])("tells %s: its title, its sentence and its pill", async (_name, entry, title, sentence, pill, kind) => {
    serve([entry]);
    open();

    const row = (await screen.findAllByTestId("notification"))[0] as HTMLElement;
    expect(within(row).getByText(title)).toBeInTheDocument();
    expect(row).toHaveTextContent(sentence);
    expect(within(row).getByText(pill, { selector: "span" })).toBeInTheDocument();
    expect(row).toHaveAttribute("data-kind", kind);
  });

  it("writes the time of an item as the panel writes a clock, in UTC", async () => {
    serve([item({ occurred_at: new Date(NOW).toISOString().slice(0, 11) + "09:05:00.000Z" })]);
    open();

    expect(within((await screen.findAllByTestId("notification"))[0] as HTMLElement).getByText("09:05")).toBeInTheDocument();
  });

  it("links a missing or read-only key to Link exchange, and a discrepancy to Review, and nothing else", async () => {
    serve([
      item({ kind: "NOTICE", event: "OPENING_REFUSED", reason: "EXCHANGE_HAS_NO_KEY" }),
      item({ kind: "NOTICE", event: "OPENING_REFUSED", reason: "EXCHANGE_KEY_READ_ONLY" }),
      item({ kind: "NOTICE", event: "OPENING_REFUSED", reason: "MARGIN_NOT_ISOLATED" }),
      item({ kind: "DISCREPANCY", event: "DISCREPANCY", reason: "NO_MATCHING_ALLOCATION" }),
      item(),
    ]);
    open();

    await screen.findAllByTestId("notification");
    const [noKey, readOnly, margin, discrepancy, opening] = rows() as [HTMLElement, HTMLElement, HTMLElement, HTMLElement, HTMLElement];
    expect(within(noKey).getByRole("link", { name: "Link exchange" })).toHaveAttribute("href", "/exchanges");
    expect(within(readOnly).getByRole("link", { name: "Link exchange" })).toHaveAttribute("href", "/exchanges");
    expect(within(margin).queryByRole("link")).not.toBeInTheDocument();
    expect(within(discrepancy).getByRole("link", { name: "Review" })).toHaveAttribute("href", "/discrepancies");
    expect(within(opening).queryByRole("link")).not.toBeInTheDocument();
  });

  it("marks a discrepancy as visible to administrators only", async () => {
    serve([item({ kind: "DISCREPANCY", event: "DISCREPANCY", reason: "NO_MATCHING_ALLOCATION" })]);
    open();

    expect(await screen.findByText("Visible to administrators only")).toBeInTheDocument();
  });

  it("groups the items by day, newest first: Today, Yesterday, then the date", async () => {
    serve([
      item({ occurred_at: TODAY, strategy_name: "First" }),
      item({ occurred_at: YESTERDAY, strategy_name: "Second" }),
      item({ occurred_at: "2025-12-30T10:00:00Z", strategy_name: "Third" }),
    ]);
    open();

    await screen.findAllByTestId("notification");
    const headings = screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent);
    expect(headings).toEqual([
      expect.stringMatching(/^Today, [A-Z][a-z]+ \d{1,2}$/),
      expect.stringMatching(/^Yesterday, [A-Z][a-z]+ \d{1,2}$/),
      "December 30, 2025",
    ]);
    expect(rows().map((row) => row.querySelector("p")?.textContent)).toEqual([
      "Opening in First",
      "Opening in Second",
      "Opening in Third",
    ]);
    // One card per day: each list is named by its heading.
    expect(within(screen.getByRole("list", { name: "December 30, 2025" })).getAllByTestId("notification")).toHaveLength(1);
  });

  it("writes the headings in Spanish: Hoy, Ayer", async () => {
    await i18n.changeLanguage("es");
    serve([item({ occurred_at: TODAY }), item({ occurred_at: YESTERDAY })]);
    open();

    await screen.findAllByTestId("notification");
    const headings = screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent);
    expect(headings[0]).toMatch(/^Hoy, /);
    expect(headings[1]).toMatch(/^Ayer, /);
    expect(screen.getByRole("heading", { level: 1, name: "Notificaciones" })).toBeInTheDocument();
  });

  it("asks for All first, and each chip sends its kind", async () => {
    const asked = serve([item()]);
    open();

    await screen.findAllByTestId("notification");
    expect(asked[0]).toEqual({ kind: null, cursor: null, limit: "30" });
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");

    for (const [name, kind] of [
      ["Operations", "OPERATION"],
      ["Safety", "SAFETY"],
      ["Notices", "NOTICE"],
      ["Discrepancies", "DISCREPANCY"],
    ] as const) {
      fireEvent.click(screen.getByRole("button", { name }));
      await waitFor(() => expect(asked.at(-1)?.kind).toBe(kind));
      expect(screen.getByRole("button", { name })).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "false");
    }
  });

  it("offers the Discrepancies chip to the admin alone", async () => {
    serve([item()], { admin: false });
    open();

    await screen.findAllByTestId("notification");
    expect(screen.getByRole("button", { name: "Safety" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Discrepancies" })).not.toBeInTheDocument();
  });

  it("loads the next page of 30 with its cursor on Show more, and the button goes on the last page", async () => {
    const all = Array.from({ length: 35 }, (_, index) => item({ strategy_name: `S${index}` }));
    const asked = serve(all);
    open();

    await screen.findAllByTestId("notification");
    expect(rows()).toHaveLength(30);
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));

    await waitFor(() => expect(rows()).toHaveLength(35));
    expect(asked.at(-1)).toEqual({ kind: null, cursor: "30", limit: "30" });
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });

  it("has no Show more when the first page is the last", async () => {
    serve([item(), item()]);
    open();

    await screen.findAllByTestId("notification");
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });

  it("says it is reading while the answer is pending", async () => {
    serve([], { pending: true });
    open();

    expect(await screen.findByRole("status")).toHaveTextContent("Reading notifications…");
  });

  it("says so, as an alert with a retry, when the answer cannot be read", async () => {
    serve([], { failFeed: true });
    open();

    expect(await screen.findByRole("alert")).toHaveTextContent("Your notifications could not be read.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByTestId("notification")).not.toBeInTheDocument();
  });

  it("says there is nothing yet when the feed is empty", async () => {
    serve([]);
    open();

    expect(await screen.findByText("Nothing to show here yet.")).toBeInTheDocument();
  });

  it("tells an event or a reason it does not know with a generic line, never a blank", async () => {
    serve([
      item({ event: "FUTURE_EVENT", reason: "FUTURE_REASON", strategy_name: null }),
      item({ kind: "NOTICE", event: "OPENING_REFUSED", reason: "FUTURE_REASON" }),
      item({ kind: "DISCREPANCY", event: "DISCREPANCY", reason: "FUTURE_KIND" }),
      closed("FUTURE_CAUSE"),
    ]);
    open();

    await screen.findAllByTestId("notification");
    const [unknown, refused, discrepancy, close] = rows() as [HTMLElement, HTMLElement, HTMLElement, HTMLElement];
    expect(within(unknown).getByText("Notification")).toBeInTheDocument();
    expect(unknown).toHaveTextContent("This panel has no more detail for it.");
    expect(within(refused).getByText("Opening refused in Alpha")).toBeInTheDocument();
    expect(refused).toHaveTextContent("The opening was refused. No capital was reserved.");
    expect(within(discrepancy).getByText("Discrepancy on Bybit")).toBeInTheDocument();
    expect(discrepancy).toHaveTextContent("Reconciliation found a difference that needs your decision.");
    expect(within(close).getByText("Close in Alpha")).toBeInTheDocument();
  });

  it("puts the amber dot of a rehearsal by its pair, and none on a live operation", async () => {
    serve([item({ rehearsal: true }), item({ rehearsal: false })]);
    open();

    await screen.findAllByTestId("notification");
    const [rehearsal, live] = rows() as [HTMLElement, HTMLElement];
    const dot = within(rehearsal).getByRole("img", { name: "Dry run" });
    expect(dot.querySelector("[data-dot]")).toHaveClass("bg-decision");
    expect(within(live).queryByRole("img", { name: "Dry run" })).not.toBeInTheDocument();
  });

  it("reads a manual close as closed manually, with the grey person, and is an Operation", async () => {
    serve([closed("MANUAL_CLOSE", { pnl: "12.6" })]);
    open();

    const row = (await screen.findAllByTestId("notification"))[0] as HTMLElement;
    expect(within(row).getByText("Manual close in Alpha")).toBeInTheDocument();
    expect(row).toHaveTextContent("closed manually at 110 USDT. Result +12.60 USDT.");
    expect(row.querySelector("svg.lucide-user")).toHaveClass("text-ink-3");
    expect(row).toHaveAttribute("data-kind", "OPERATION");
  });

  it("colours an item by its kind, from the notification tokens", async () => {
    serve([item(), item({ kind: "SAFETY", event: "OPENING_REFUSED", reason: "OPENING_REFUSED_ACCOUNT_SUSPENDED" })]);
    open();

    await screen.findAllByTestId("notification");
    const [operation, safety] = rows() as [HTMLElement, HTMLElement];
    expect(operation).toHaveClass("border-l-notif-operation");
    expect(safety).toHaveClass("border-l-notif-safety");
  });

  it("stores the instant it was opened, for this user, in this browser", async () => {
    serve([]);
    const before = Date.now();
    open();

    await screen.findByText("Nothing to show here yet.");
    await waitFor(() => {
      const stored = Object.entries(window.localStorage).filter(([key]) => key === storageKeyOf(SIGNED_IN_EMAIL));
      expect(stored).toHaveLength(1);
      expect(Date.parse(stored[0]?.[1] ?? "")).toBeGreaterThanOrEqual(before);
    });
  });
});
