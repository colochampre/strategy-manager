import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement } from "react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { fetchConfirmed, useConfirmedDiscrepancies } from "@/shared/api/discrepancies";
import { booking, confirmedBody, discrepancy, lock, unlock } from "@/test/harness";

function respond(body: unknown, status = 200) {
  const fetchMock = vi.fn(() =>
    Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) } as Response),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(unlock);
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

/** A body with every list filled: two items that need the owner, one being booked, one booking. */
function fullBody() {
  return confirmedBody({
    needs_owner: [
      discrepancy(),
      discrepancy({
        exchange: "binance",
        symbol: "LINKUSDT",
        kind: "NO_MATCHING_ALLOCATION",
        reason: "NOT_BOOKABLE",
        venue_net_base: "12",
        ledger_net_base: "0",
        allocations: [],
        confirmed_at: null,
      }),
    ],
    being_booked: [discrepancy({ reason: null, kind: "ATTRIBUTABLE_SINGLE_ALLOCATION" })],
    booked: [booking({ discrepancy_open: true }), booking({ decided_by: "owner" })],
  });
}

function without<T extends object>(value: T, key: keyof T): unknown {
  return Object.fromEntries(Object.entries(value).filter(([name]) => name !== key));
}

describe("fetchConfirmed", () => {
  it("returns a well-formed body as the route sent it, every list and the count", async () => {
    const body = fullBody();
    respond(body);

    expect(await fetchConfirmed()).toEqual(body);
  });

  it("asks GET /reconciliation/confirmed and nothing else, without a parameter", async () => {
    const fetchMock = respond(confirmedBody());

    await fetchConfirmed();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit | undefined];
    expect(url.endsWith("/reconciliation/confirmed")).toBe(true);
    expect(init?.method ?? "GET").toBe("GET");
  });

  it("reads a body whose lists are empty, and one read in dry run", async () => {
    respond(confirmedBody({ dry_run: true }));

    expect(await fetchConfirmed()).toEqual(confirmedBody({ dry_run: true }));
  });

  it("accepts an allocation whose strategy is unknown, and a discrepancy never confirmed", async () => {
    const body = confirmedBody({
      needs_owner: [
        discrepancy({
          allocations: [{ allocation_id: "allocation-9", strategy_id: null, strategy_name: null }],
          confirmed_at: null,
        }),
      ],
      booked: [booking({ strategy_name: null })],
    });
    respond(body);

    expect(await fetchConfirmed()).toEqual(body);
  });

  it.each([
    [
      "booked",
      (): unknown => ({ ...fullBody(), booked: [booking(), { ...booking(), quantity: 0.5 }] }),
    ],
    [
      "booked, a field missing",
      (): unknown => ({ ...fullBody(), booked: [booking(), without(booking(), "proposal_id")] }),
    ],
    [
      "needs_owner",
      (): unknown => ({ ...fullBody(), needs_owner: [discrepancy(), { ...discrepancy(), kind: "SOMETHING_NEW" }] }),
    ],
    [
      "needs_owner, a field missing",
      (): unknown => ({ ...fullBody(), needs_owner: [discrepancy(), without(discrepancy(), "last_observed_at")] }),
    ],
    [
      "being_booked",
      (): unknown => ({ ...fullBody(), being_booked: [discrepancy({ reason: null }), { ...discrepancy(), allocations: "none" }] }),
    ],
    [
      "being_booked, a reason that is not a reason",
      (): unknown => ({ ...fullBody(), being_booked: [{ ...discrepancy(), reason: "MAYBE" }] }),
    ],
  ])("refuses the WHOLE body when one element of %s is malformed, and returns none of the good ones", async (_label, make) => {
    respond(make());

    await expect(fetchConfirmed()).rejects.toBeInstanceOf(ApiError);
  });

  it.each([
    ["an array where the object belongs", []],
    ["a null body", null],
    ["a body without dry_run", without(confirmedBody(), "dry_run")],
    ["a dry_run that is not a boolean", { ...confirmedBody(), dry_run: "false" }],
    ["a read_at that is not an instant", { ...confirmedBody(), read_at: "yesterday" }],
    ["a count that is not a number", { ...confirmedBody(), needs_owner_count: "2" }],
    ["a missing list", without(confirmedBody(), "being_booked")],
    ["a list that is not a list", { ...confirmedBody(), booked: { items: [] } }],
  ])("refuses %s, never reads it as nothing needing the owner", async (_label, body) => {
    respond(body);

    await expect(fetchConfirmed()).rejects.toBeInstanceOf(ApiError);
  });

  it("treats a 404 as an error, never as an empty answer", async () => {
    respond({ detail: "Not Found" }, 404);

    await expect(fetchConfirmed()).rejects.toMatchObject({ name: "ApiError", status: 404 });
  });

  it("treats a 500 and a network failure as errors", async () => {
    respond({ detail: "down" }, 500);
    await expect(fetchConfirmed()).rejects.toMatchObject({ status: 500 });

    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("offline"))));
    await expect(fetchConfirmed()).rejects.toBeInstanceOf(ApiError);
  });
});

function renderConfirmed() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
  const view = renderHook(() => useConfirmedDiscrepancies(), { wrapper });
  return { client, ...view };
}

describe("useConfirmedDiscrepancies", () => {
  it("reads under the key ['reconciliation','confirmed'], stale and refetched every 60 s, with the client's focus default", () => {
    respond(confirmedBody());

    const { client } = renderConfirmed();

    const query = client.getQueryCache().find({ queryKey: ["reconciliation", "confirmed"] });
    expect(query).toBeDefined();
    // The cache's `options` type is the base one; the observer's options (stale time, interval) ride on the same object.
    const options = query?.options as unknown as Record<string, unknown> | undefined;
    expect(options?.staleTime).toBe(60_000);
    expect(options?.refetchInterval).toBe(60_000);
    expect(options?.refetchOnWindowFocus).toBeUndefined();
    expect(client.getQueryCache().getAll()).toHaveLength(1);
  });

  it("holds the whole body as data once it is read", async () => {
    const body = fullBody();
    respond(body);

    const { result } = renderConfirmed();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(body);
  });

  it("is the failed state, with no data, for a malformed body: never 'nothing needs you'", async () => {
    respond({ ...confirmedBody(), needs_owner: [{ ...discrepancy(), kind: "SOMETHING_NEW" }] });

    const { result } = renderConfirmed();

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });
});
