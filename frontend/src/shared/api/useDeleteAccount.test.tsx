import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider, onlineManager, useQuery } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAccountDeletedStore } from "@/shared/account/account-deleted";
import { apiFetch } from "@/shared/api/client";
import { useDeleteAccount } from "@/shared/api/me";
import { jsonResponse } from "@/test/harness";

const POLL_MS = 10;

/** A poll like the panel's (every query refetches on an interval), beside the deletion. */
function usePollAndDelete() {
  useQuery({ queryKey: ["poll"], queryFn: () => apiFetch<unknown>("/poll"), refetchInterval: POLL_MS });
  return useDeleteAccount();
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function mount() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return renderHook(() => usePollAndDelete(), { wrapper });
}

function pollsOf(fetchMock: ReturnType<typeof vi.fn>): number {
  return fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/poll")).length;
}

const sleep = (ms: number) => new Promise((done) => setTimeout(done, ms));

describe("useDeleteAccount while the deletion is in flight (the verifier's A6)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    onlineManager.setOnline(true);
    useAccountDeletedStore.setState({ deleted: false });
  });

  it("lets no poll reach the API until the answer, then the polls resume on a refusal", async () => {
    // A request that lands after the deletion commits signs the e-mail in again as a new, empty account.
    const answer = deferred<Response>();
    const fetchMock = vi.fn((_url: string, init?: RequestInit) =>
      init?.method === "DELETE" ? answer.promise : Promise.resolve(jsonResponse({})),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { result } = mount();
    await waitFor(() => expect(pollsOf(fetchMock)).toBeGreaterThan(0));

    act(() => result.current.mutate());
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(true));
    const before = pollsOf(fetchMock);
    await act(() => sleep(POLL_MS * 8));

    expect(pollsOf(fetchMock)).toBe(before);

    await act(async () => {
      answer.resolve(jsonResponse({ detail: { error: "ACCOUNT_CHANGED", message: "try again" } }, 409));
      await answer.promise;
    });
    await waitFor(() => expect(result.current.data?.kind).toBe("changed"));
    await waitFor(() => expect(pollsOf(fetchMock)).toBeGreaterThan(before));
  });

  it("keeps everything quiet once the account is deleted", async () => {
    const fetchMock = vi.fn((_url: string, init?: RequestInit) =>
      Promise.resolve(init?.method === "DELETE" ? new Response(null, { status: 204 }) : jsonResponse({})),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { result } = mount();
    await waitFor(() => expect(pollsOf(fetchMock)).toBeGreaterThan(0));

    act(() => result.current.mutate());
    await waitFor(() => expect(result.current.data?.kind).toBe("deleted"));
    const after = pollsOf(fetchMock);
    await act(() => sleep(POLL_MS * 8));

    expect(useAccountDeletedStore.getState().deleted).toBe(true);
    expect(pollsOf(fetchMock)).toBe(after);
  });
});
