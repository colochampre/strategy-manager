import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { fetchNotifications, fetchUnseen, notificationsKey, unseenKey } from "@/shared/api/notifications";
import { lock, unlock } from "@/test/harness";

const ITEM = {
  id: "opened:a1",
  kind: "OPERATION",
  event: "OPENED",
  occurred_at: "2026-11-27T09:00:00Z",
  reason: null,
  strategy_id: "s1",
  strategy_name: "Alpha",
  exchange: "bybit",
  venue: "usdt-m",
  pair: "SOLUSDT",
  side: "LONG",
  rehearsal: false,
  currency: "USDT",
  entry_price: "100",
  exit_price: null,
  pnl: null,
  leverage: "3",
  close_cause: null,
  detail: {},
};

function respond(body: unknown, status = 200) {
  const fetchMock = vi.fn((_input: RequestInfo | URL) =>
    Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) } as Response),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function askedOf(fetchMock: ReturnType<typeof respond>) {
  return new URL(String(fetchMock.mock.calls[0]?.[0]), "http://x");
}

beforeEach(unlock);
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

describe("fetchNotifications", () => {
  it("asks for 30 with no cursor and no kind when none is set", async () => {
    const fetchMock = respond({ items: [ITEM], next_cursor: "c1" });

    const page = await fetchNotifications({ kind: null, cursor: null });

    expect(page.next_cursor).toBe("c1");
    const url = askedOf(fetchMock);
    expect(url.pathname).toMatch(/\/notifications$/);
    expect(Object.fromEntries(url.searchParams)).toEqual({ limit: "30" });
  });

  it("sends the cursor and the kind when they are set", async () => {
    const fetchMock = respond({ items: [], next_cursor: null });

    await fetchNotifications({ kind: "SAFETY", cursor: "c1" });

    expect(Object.fromEntries(askedOf(fetchMock).searchParams)).toEqual({ limit: "30", cursor: "c1", kind: "SAFETY" });
  });

  it("throws on a body that is not a page, so a failed read never reads as an empty feed", async () => {
    respond({ items: [{ ...ITEM, kind: "MYSTERY" }], next_cursor: null });
    await expect(fetchNotifications({ kind: null, cursor: null })).rejects.toBeInstanceOf(ApiError);

    respond({ items: [{ ...ITEM, detail: { a: 1 } }], next_cursor: null });
    await expect(fetchNotifications({ kind: null, cursor: null })).rejects.toBeInstanceOf(ApiError);

    respond({ items: [], next_cursor: 5 });
    await expect(fetchNotifications({ kind: null, cursor: null })).rejects.toBeInstanceOf(ApiError);
  });

  it("keeps an event and a reason this build does not know, to be told generically", async () => {
    respond({ items: [{ ...ITEM, event: "FUTURE_EVENT", reason: "FUTURE_REASON" }], next_cursor: null });
    const page = await fetchNotifications({ kind: null, cursor: null });
    expect(page.items[0]?.event).toBe("FUTURE_EVENT");
  });

  it("keys the feed by its kind", () => {
    expect(notificationsKey(null)).not.toEqual(notificationsKey("SAFETY"));
  });
});

describe("fetchUnseen", () => {
  it("asks since the instant and answers the kinds", async () => {
    const fetchMock = respond({ kinds: ["SAFETY", "OPERATION"] });

    const kinds = await fetchUnseen("2026-11-27T08:00:00.000Z");

    expect(kinds).toEqual(["SAFETY", "OPERATION"]);
    const url = askedOf(fetchMock);
    expect(url.pathname).toMatch(/\/notifications\/unseen$/);
    expect(url.searchParams.get("since")).toBe("2026-11-27T08:00:00.000Z");
  });

  it("throws on a body that is not a list of known kinds", async () => {
    respond({ kinds: ["SAFETY", "MYSTERY"] });
    await expect(fetchUnseen("2026-11-27T08:00:00.000Z")).rejects.toBeInstanceOf(ApiError);
  });

  it("keys the read by its instant", () => {
    expect(unseenKey("a")).not.toEqual(unseenKey("b"));
  });
});
