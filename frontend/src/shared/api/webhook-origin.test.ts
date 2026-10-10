import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import cases from "@/features/strategies/webhook-origin.cases.json";
import { ApiError } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
import { acceptedOrigin, fetchWebhookOrigin, useWebhookOrigin } from "@/shared/api/webhook-origin";
import { useTokenStore } from "@/shared/auth/token-store";
import { jsonResponse } from "@/test/harness";

function stubFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse(body, status));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function clientWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
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

describe("fetchWebhookOrigin", () => {
  it("requests GET /webhook-origin and answers the origin", async () => {
    const fetchMock = stubFetch({ origin: "https://example.org" });

    const origin = await fetchWebhookOrigin();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/webhook-origin`);
    expect(call[1].method).toBeUndefined();
    expect(origin).toBe("https://example.org");
  });

  it('accepts {"origin": null} as no host', async () => {
    const fetchMock = stubFetch({ origin: null });

    await expect(fetchWebhookOrigin()).resolves.toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["a body without origin", {}],
    ["an origin that is a number", { origin: 5 }],
    ["an origin that is a boolean", { origin: true }],
    ["a body that is a list", ["https://example.org"]],
    ["a body that is null", null],
  ])("refuses %s", async (_name, body) => {
    stubFetch(body);

    await expect(fetchWebhookOrigin()).rejects.toBeInstanceOf(ApiError);
  });

  it("reads a served value that is not a serialised origin as no host", async () => {
    stubFetch({ origin: "https://example.org/hook" });

    await expect(fetchWebhookOrigin()).resolves.toBeNull();
  });

  it("throws the refusal of an older API (404) as an ApiError with its status", async () => {
    stubFetch({ detail: "Not Found" }, 404);

    const failure = await fetchWebhookOrigin().then(
      () => null,
      (error: unknown) => error,
    );

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(404);
  });
});

describe("acceptedOrigin", () => {
  it.each(cases.accepted.map((entry) => [entry.origin]))(
    "the panel accepts every normalised case of the shared list: %s",
    (origin) => {
      expect(acceptedOrigin(origin as string)).toBe(origin);
    },
  );

  it.each([
    ["a path", "https://example.org/hook"],
    ["a query", "https://example.org?x=1"],
    ["a fragment", "https://example.org#top"],
    ["a user", "https://user@example.org"],
    ["a user and a password", "https://user:pass@example.org"],
    ["a trailing slash", "https://example.org/"],
    ["upper case", "HTTPS://Example.ORG"],
    ["the default port", "https://example.org:443"],
    ["no scheme", "example.org"],
    ["an empty text", ""],
    ["a port out of range", "https://example.org:99999"],
  ])("the panel refuses what is not an origin: %s", (_name, value) => {
    expect(acceptedOrigin(value)).toBeNull();
  });
});

describe("useWebhookOrigin", () => {
  it("is keyed ['webhook-origin'] and requests the route once mounted", async () => {
    const fetchMock = stubFetch({ origin: "http://localhost:8000" });
    const { client, wrapper } = clientWrapper();
    expect(fetchMock).not.toHaveBeenCalled();

    const { result } = renderHook(() => useWebhookOrigin(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.data).toBe("http://localhost:8000");
    expect(client.getQueryData(["webhook-origin"])).toBe("http://localhost:8000");
  });

  it("reads an older API's 404 as an error, so the page can say the host could not be loaded", async () => {
    stubFetch({ detail: "Not Found" }, 404);
    const { wrapper } = clientWrapper();
    const { result } = renderHook(() => useWebhookOrigin(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.data).toBeUndefined();
  });
});
