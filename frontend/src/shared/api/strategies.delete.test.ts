import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
import { deleteStrategy, useDeleteStrategy } from "@/shared/api/strategies";
import { useTokenStore } from "@/shared/auth/token-store";
import { jsonResponse } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const OTHER_ID = "22222222-2222-4222-8222-222222222222";

const NO_CONTENT = { ok: true, status: 204, json: () => Promise.reject(new Error("no body")) } as Response;

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function clientWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
  return { client, wrapper };
}

beforeEach(() => {
  useTokenStore.setState({ token: "a-token" });
});
afterEach(() => {
  vi.unstubAllGlobals();
  useTokenStore.setState({ token: null });
});

describe("deleteStrategy", () => {
  it("sends DELETE /api/strategies/{id} and resolves on a 204", async () => {
    const fetchMock = stubFetch(NO_CONTENT);

    await expect(deleteStrategy(ID)).resolves.toBeUndefined();

    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/strategies/${ID}`);
    expect(call[1].method).toBe("DELETE");
  });
});

describe("useDeleteStrategy", () => {
  it("removes the deleted strategy's queries instead of refetching them", async () => {
    stubFetch(NO_CONTENT);
    const { client, wrapper } = clientWrapper();
    client.setQueryData(["strategy", ID], { id: ID });
    client.setQueryData(["strategy", ID, "events"], []);
    client.setQueryData(["strategy", OTHER_ID], { id: OTHER_ID });
    const { result } = renderHook(() => useDeleteStrategy(ID), { wrapper });

    result.current.mutate();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryData(["strategy", ID])).toBeUndefined();
    expect(client.getQueryData(["strategy", ID, "events"])).toBeUndefined();
    expect(client.getQueryData(["strategy", OTHER_ID])).toEqual({ id: OTHER_ID });
  });

  it("does not invalidate the deleted strategy's own query, which would refetch a 404", async () => {
    stubFetch(NO_CONTENT);
    const { client, wrapper } = clientWrapper();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useDeleteStrategy(ID), { wrapper });

    result.current.mutate();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = invalidate.mock.calls.map((call) => call[0]?.queryKey);
    expect(keys).toEqual([["strategies"]]);
  });

  it("invalidates both strategies lists on success", async () => {
    stubFetch(NO_CONTENT);
    const { client, wrapper } = clientWrapper();
    client.setQueryData(["strategies", { includeArchived: false }], [{ id: ID }]);
    client.setQueryData(["strategies", { includeArchived: true }], [{ id: ID }]);
    const { result } = renderHook(() => useDeleteStrategy(ID), { wrapper });

    result.current.mutate();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(client.getQueryState(["strategies", { includeArchived: false }])?.isInvalidated).toBe(true);
    expect(client.getQueryState(["strategies", { includeArchived: true }])?.isInvalidated).toBe(true);
  });

  it("treats a 404 as already deleted and runs the same cache effects", async () => {
    stubFetch(jsonResponse({ detail: `no strategy registered under id ${ID}` }, 404));
    const { client, wrapper } = clientWrapper();
    client.setQueryData(["strategy", ID], { id: ID });
    client.setQueryData(["strategies", { includeArchived: false }], [{ id: ID }]);
    const { result } = renderHook(() => useDeleteStrategy(ID), { wrapper });

    result.current.mutate();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.error).toBeNull();
    expect(client.getQueryData(["strategy", ID])).toBeUndefined();
    expect(client.getQueryState(["strategies", { includeArchived: false }])?.isInvalidated).toBe(true);
  });

  it("keeps the code and the history counts of a 409, and touches no cache", async () => {
    const history = {
      signals: 3,
      reservations: 0,
      execution_attempts: 0,
      ledger_entries: 2,
      booking_proposals: 0,
      enablement_events: 0,
    };
    stubFetch(
      jsonResponse({ detail: { error: "HAS_HISTORY", message: "has history", history } }, 409),
    );
    const { client, wrapper } = clientWrapper();
    client.setQueryData(["strategy", ID], { id: ID });
    const { result } = renderHook(() => useDeleteStrategy(ID), { wrapper });

    result.current.mutate();
    await waitFor(() => expect(result.current.isError).toBe(true));

    const error = result.current.error;
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
    expect((error as ApiError).code).toBe("HAS_HISTORY");
    expect((error as ApiError).fields?.history).toEqual(history);
    expect(client.getQueryData(["strategy", ID])).toEqual({ id: ID });
  });
});
