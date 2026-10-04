import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StrategyDetailPage } from "@/features/strategies/StrategyDetailPage";
import { webhookMessage } from "@/features/strategies/webhook-message";
import { WebhookMessage } from "@/features/strategies/WebhookMessage";
import i18n from "@/shared/i18n";
import { jsonResponse, lock, renderAt, resetExchangeScope, stubApi, strategyRoute, unlock } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const OTHER_ID = "22222222-2222-4222-8222-222222222222";
const SECRET = "s3cr3t-Vh4lu3-Zq9";
const URL_BASE = "/webhook/tradingview?secret=";
const PLACEHOLDER_URL = `${URL_BASE}<your WEBHOOK_SECRET>`;
const SECRET_PATH = "/api/webhook-secret";
const CONSOLE_METHODS = ["log", "info", "warn", "error", "debug"] as const;

type Answer = () => Promise<Response>;
const answersWith =
  (secret: unknown): Answer =>
  () =>
    Promise.resolve(jsonResponse({ secret }));

interface Call {
  url: string;
  init: RequestInit | undefined;
}

/** A QueryClient with the app's own defaults (main.tsx builds a bare one), so window-focus refetching is live. */
function setup(answer: Answer = answersWith(SECRET), strategyId = ID) {
  const calls: Call[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return answer();
  });
  vi.stubGlobal("fetch", fetchMock);
  const queryClient = new QueryClient();
  const view = render(
    <QueryClientProvider client={queryClient}>
      <WebhookMessage strategyId={strategyId} />
    </QueryClientProvider>,
  );
  const secretCalls = () => calls.filter((call) => call.url.endsWith(SECRET_PATH));
  return { queryClient, calls, secretCalls, ...view };
}

/**
 * A disabled `useQuery` still puts an empty entry in the cache, so "holds no secret" means no
 * entry holds data, and an eviction is proved separately by the entry count after unmounting.
 */
const cachedData = (queryClient: QueryClient) => queryClient.getQueryCache().findAll().map((query) => query.state.data);

const showButton = () => screen.getByRole("button", { name: "Show secret" });
const revealedUrl = (secret = SECRET) => screen.findByText(`${URL_BASE}${secret}`);
const messageText = () => screen.getByRole("group", { name: "Alert message" }).textContent;

const consoleSpies = CONSOLE_METHODS.map((method) => vi.spyOn(console, method).mockImplementation(() => undefined));

beforeEach(() => {
  unlock();
  resetExchangeScope();
  for (const spy of consoleSpies) spy.mockClear();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  window.sessionStorage.clear();
  focusManager.setFocused(undefined);
  await i18n.changeLanguage("en");
});

describe("WebhookMessage", () => {
  it("test_url_shows_placeholder_by_default_not_the_secret", async () => {
    const { secretCalls, queryClient } = setup();

    expect(screen.getByText(PLACEHOLDER_URL)).toBeInTheDocument();
    expect(showButton()).toBeEnabled();
    // Give any mount-time request the chance it would need to be sent and to resolve.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

    expect(secretCalls()).toHaveLength(0);
    expect(cachedData(queryClient).filter((data) => data !== undefined)).toEqual([]);
    expect(document.body.textContent).not.toContain(SECRET);
  });

  it("renders the copy-ready alert message for the strategy, and it never changes with the secret", async () => {
    setup();

    expect(messageText()).toBe(webhookMessage(ID));
    expect(JSON.parse(messageText() ?? "")).toMatchObject({ signal_type: ID, symbol: "{{ticker}}" });

    fireEvent.click(showButton());
    await revealedUrl();

    expect(messageText()).toBe(webhookMessage(ID));
  });

  it("test_show_secret_click_fetches_get_webhook_secret_substitutes_in_place", async () => {
    const { secretCalls } = setup();

    fireEvent.click(showButton());

    expect(await revealedUrl()).toBeInTheDocument();
    expect(screen.queryByText(PLACEHOLDER_URL)).not.toBeInTheDocument();
    expect(secretCalls()).toHaveLength(1);
    const call = secretCalls()[0];
    expect(call?.url.endsWith(SECRET_PATH)).toBe(true);
    expect(call?.init?.method ?? "GET").toBe("GET");
    expect(new Headers(call?.init?.headers).get("Authorization")).toBe("Bearer test-token");
    expect(call?.url).not.toContain(SECRET);
    expect(screen.getByRole("button", { name: "Hide secret" })).toBeInTheDocument();
  });

  it("puts a secret that is not URL-safe into the URL percent-encoded", async () => {
    setup(answersWith("a&b+c d=e"));

    fireEvent.click(showButton());

    expect(await screen.findByText(`${URL_BASE}a%26b%2Bc%20d%3De`)).toBeInTheDocument();
  });

  it("test_no_other_control_ever_requests_the_secret", async () => {
    const requests: string[] = [];
    const strategy = strategyRoute(ID, "ETH Breakout");
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } }, [], undefined, {}, (url, init) => {
      requests.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith(SECRET_PATH)) return Promise.resolve(jsonResponse({ secret: SECRET }));
      return strategy(url, init);
    });
    renderAt(
      <Routes>
        <Route path="strategies/:strategyId" element={<StrategyDetailPage />} />
      </Routes>,
      `/strategies/${ID}`,
    );
    await screen.findByRole("heading", { level: 1, name: "ETH Breakout" });
    fireEvent.click(screen.getByRole("button", { name: "Connect a TradingView alert" }));
    const secretRequests = () => requests.filter((request) => request.includes("webhook-secret"));

    const others = screen
      .getAllByRole("button")
      .filter((button) => !["Show secret", "Connect a TradingView alert"].includes(button.textContent ?? ""));
    expect(others.length).toBeGreaterThan(3);
    for (const button of others) {
      fireEvent.click(button);
      fireEvent.keyDown(document.body, { key: "Escape" });
    }
    fireEvent.click(screen.getByText(PLACEHOLDER_URL));
    fireEvent.click(screen.getByRole("group", { name: "Alert message" }));
    act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
      window.dispatchEvent(new Event("online"));
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30));
    });

    expect(secretRequests()).toEqual([]);
    expect(document.body.textContent).not.toContain(SECRET);

    fireEvent.click(screen.getByRole("button", { name: "Show secret" }));
    await revealedUrl();

    expect(secretRequests()).toHaveLength(1);
    expect(secretRequests()[0]?.startsWith("GET ")).toBe(true);
  });

  it("does not fetch again when the window regains focus or the network returns after the secret is shown", async () => {
    const { secretCalls } = setup();
    fireEvent.click(showButton());
    await revealedUrl();

    act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
      window.dispatchEvent(new Event("online"));
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30));
    });

    expect(secretCalls()).toHaveLength(1);
  });

  it("test_leaving_the_view_restores_placeholder_and_evicts_query_cache", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", (input: RequestInfo | URL) => {
      calls.push(String(input));
      return Promise.resolve(jsonResponse({ secret: SECRET }));
    });
    const queryClient = new QueryClient();
    const view = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[`/strategies/${ID}`]}>
          <Routes>
            <Route
              path="strategies/:strategyId"
              element={
                <>
                  <Link to="/strategies">leave</Link>
                  <WebhookMessage strategyId={ID} />
                </>
              }
            />
            <Route path="strategies" element={<Link to={`/strategies/${ID}`}>return</Link>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Show secret" }));
    await revealedUrl();
    expect(queryClient.getQueryCache().findAll()).toHaveLength(1);

    fireEvent.click(screen.getByRole("link", { name: "leave" }));

    expect(screen.queryByText(`${URL_BASE}${SECRET}`)).not.toBeInTheDocument();
    expect(queryClient.getQueryCache().findAll()).toHaveLength(0);
    expect(queryClient.getQueryData(["webhook-secret"])).toBeUndefined();

    fireEvent.click(screen.getByRole("link", { name: "return" }));

    expect(screen.getByText(PLACEHOLDER_URL)).toBeInTheDocument();
    expect(calls).toHaveLength(1);

    // Unmounting the whole tree (a closed tab, a route outside this router) evicts it too.
    fireEvent.click(screen.getByRole("button", { name: "Show secret" }));
    await revealedUrl();
    expect(queryClient.getQueryCache().findAll()).toHaveLength(1);
    view.unmount();
    expect(queryClient.getQueryCache().findAll()).toHaveLength(0);
  });

  it("hides the secret and evicts it from the cache on Hide, and shows it again only on another click", async () => {
    const { queryClient, secretCalls } = setup();
    fireEvent.click(showButton());
    await revealedUrl();

    fireEvent.click(screen.getByRole("button", { name: "Hide secret" }));

    expect(screen.getByText(PLACEHOLDER_URL)).toBeInTheDocument();
    expect(screen.queryByText(`${URL_BASE}${SECRET}`)).not.toBeInTheDocument();
    expect(queryClient.getQueryData(["webhook-secret"])).toBeUndefined();
    expect(cachedData(queryClient).filter((data) => data !== undefined)).toEqual([]);

    fireEvent.click(showButton());
    await revealedUrl();

    expect(secretCalls()).toHaveLength(2);
  });

  it("starts from the placeholder for another strategy, as the secret belongs to the view it was asked for", async () => {
    const { queryClient, rerender } = setup();
    fireEvent.click(showButton());
    await revealedUrl();

    rerender(
      <QueryClientProvider client={queryClient}>
        <WebhookMessage strategyId={OTHER_ID} />
      </QueryClientProvider>,
    );

    expect(screen.getByText(PLACEHOLDER_URL)).toBeInTheDocument();
    expect(queryClient.getQueryData(["webhook-secret"])).toBeUndefined();
    expect(messageText()).toBe(webhookMessage(OTHER_ID));

    fireEvent.click(showButton());

    expect(await revealedUrl()).toBeInTheDocument();
  });

  it("leaves nothing in the cache when the view is left while the request is still in flight", async () => {
    let resolveAnswer: (response: Response) => void = () => undefined;
    const { queryClient, unmount } = setup(() => new Promise<Response>((resolve) => (resolveAnswer = resolve)));
    fireEvent.click(showButton());
    await waitFor(() => expect(queryClient.getQueryCache().findAll()).toHaveLength(1));

    unmount();
    await act(async () => {
      resolveAnswer(jsonResponse({ secret: SECRET }));
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

    expect(queryClient.getQueryCache().findAll()).toHaveLength(0);
    expect(queryClient.getQueryData(["webhook-secret"])).toBeUndefined();
  });

  it("says the secret could not be loaded on a refusal, keeps the placeholder and sends no retry", async () => {
    const { secretCalls, queryClient } = setup(() => Promise.resolve(jsonResponse({ detail: "the webhook secret is not configured" }, 503)));

    fireEvent.click(showButton());

    expect(await screen.findByRole("alert")).toHaveTextContent("The secret could not be loaded. The URL still shows the placeholder.");
    expect(screen.getByText(PLACEHOLDER_URL)).toBeInTheDocument();
    expect(secretCalls()).toHaveLength(1);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30));
    });
    expect(secretCalls()).toHaveLength(1);
    expect(queryClient.getQueryData(["webhook-secret"])).toBeUndefined();
  });

  it("asks again only when the owner clicks Show secret again after a failure", async () => {
    let attempt = 0;
    const { secretCalls } = setup(() => {
      attempt += 1;
      return attempt === 1 ? Promise.reject(new TypeError("offline")) : Promise.resolve(jsonResponse({ secret: SECRET }));
    });
    fireEvent.click(showButton());
    await screen.findByRole("alert");

    fireEvent.click(showButton());

    expect(await revealedUrl()).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(secretCalls()).toHaveLength(2);
  });

  it.each([
    ["an empty secret", { secret: "" }],
    ["a secret that is not a string", { secret: 12345 }],
    ["a body without a secret", { other: "leaked-value-123" }],
  ])("treats %s as a failure and shows nothing from the body", async (_name, body) => {
    setup(() => Promise.resolve(jsonResponse(body)));

    fireEvent.click(showButton());

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(PLACEHOLDER_URL)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("12345");
    expect(document.body.textContent).not.toContain("leaked-value-123");
  });

  it("never lets the secret reach a console call, a storage, a query key or a request URL", async () => {
    const { queryClient, calls } = setup();
    fireEvent.click(showButton());
    await revealedUrl();
    fireEvent.click(screen.getByRole("button", { name: "Hide secret" }));
    fireEvent.click(showButton());
    await revealedUrl();

    for (const spy of consoleSpies) expect(JSON.stringify(spy.mock.calls)).not.toContain(SECRET);
    expect(JSON.stringify({ ...window.localStorage })).not.toContain(SECRET);
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain(SECRET);
    expect(JSON.stringify(queryClient.getQueryCache().findAll().map((query) => query.queryKey))).not.toContain(SECRET);
    expect(calls.every((call) => !call.url.includes(SECRET))).toBe(true);
  });

  it("renders its texts in Spanish", async () => {
    await i18n.changeLanguage("es");
    setup();

    expect(screen.getByRole("button", { name: "Mostrar el secreto" })).toBeInTheDocument();
    expect(screen.getByText(`${URL_BASE}<su WEBHOOK_SECRET>`)).toBeInTheDocument();
  });
});
