import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
/** A secret that needs percent-encoding, and that is easy to search for if it leaks. */
const AWKWARD = "p&q/r s";
const AWKWARD_ENCODED = "p%26q%2Fr%20s";
const URL_BASE = "/webhook/tradingview?secret=";
const PLACEHOLDER_URL = `${URL_BASE}<your WEBHOOK_SECRET>`;
const SECRET_PATH = "/api/webhook-secret";
const ORIGIN_PATH = "/api/webhook-origin";
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

/**
 * A QueryClient with the app's own defaults (main.tsx builds a bare one), so window-focus refetching is live.
 * The block also reads the webhook's host when it opens; these tests are about the secret, so the host route
 * answers "no host configured" and `answer` is for every other route.
 */
function setup(answer: Answer = answersWith(SECRET), strategyId = ID) {
  const calls: Call[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return String(input).endsWith(ORIGIN_PATH) ? Promise.resolve(jsonResponse({ origin: null })) : answer();
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
const cachedData = (queryClient: QueryClient) =>
  queryClient.getQueryCache().findAll({ queryKey: ["webhook-secret"] }).map((query) => query.state.data);
/** The secret's entries only: the webhook's host is cached too, and is not what an eviction removes. */
const secretEntries = (queryClient: QueryClient) => queryClient.getQueryCache().findAll({ queryKey: ["webhook-secret"] });

const HOST = "https://example.duckdns.org";
const HOST_UNSET =
  "No public host is configured for the webhook, so only the path is shown. Put your webhook's host in front of it.";
const HOST_ERROR = "The webhook's host could not be loaded, so only the path is shown.";
const COPY_FAILED = "Could not copy. Select the text and copy it by hand.";
const originAnswers =
  (origin: unknown): Answer =>
  () =>
    Promise.resolve(jsonResponse({ origin }));

/** The block, with the origin route answered by `origin` and the secret route by `secret`. */
function setupHost(origin: Answer, secret: Answer = answersWith(SECRET)) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      return url.endsWith(ORIGIN_PATH) ? origin() : secret();
    }),
  );
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <WebhookMessage strategyId={ID} />
    </QueryClientProvider>,
  );
  return { calls, queryClient, ...view };
}
const secretCallsOf = (calls: Call[]) => calls.filter((call) => call.url.endsWith(SECRET_PATH));
const urlText = () => screen.getByLabelText("Webhook URL").textContent;
const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 30));
  });

/** `navigator.clipboard`, which jsdom lacks: a spy that resolves, a spy that rejects, or none at all. */
function setClipboard(clipboard: unknown): void {
  Object.defineProperty(navigator, "clipboard", { value: clipboard, configurable: true });
}
function stubClipboard(): ReturnType<typeof vi.fn> {
  const writeText = vi.fn().mockResolvedValue(undefined);
  setClipboard({ writeText });
  return writeText;
}

// A Copy button is found by its place and not by its name: its name becomes "Copied" once it is used
// (12f.10.30d). The URL's is the last button in the URL's row; the message's is the only one under it.
const copyUrl = () => {
  const urlRow = screen.getByLabelText(i18n.t("strategies.webhook.urlLabel")).parentElement as HTMLElement;
  const buttons = within(urlRow).getAllByRole("button");
  return buttons[buttons.length - 1] as HTMLElement;
};
const copyMessage = () =>
  within(
    screen.getByRole("group", { name: i18n.t("strategies.webhook.messageLabel") }).parentElement as HTMLElement,
  ).getByRole("button");
/** How many buttons read "Copied" right now: the visible places where it stands. */
const copiedCount = () => screen.queryAllByRole("button", { name: "Copied" }).length;
/** How many status regions say "Copied" right now: what a screen reader is told. */
const announcedCount = () => screen.queryAllByRole("status").filter((node) => node.textContent === "Copied").length;
/** The status region that shares a row with `button`: each button owns one. */
const statusBeside = (button: HTMLElement) => within(button.parentElement as HTMLElement).getByRole("status");
/** A click, then the microtasks of the write it starts. */
const press = (button: HTMLElement) =>
  act(async () => {
    fireEvent.click(button);
  });
const hideButton = () => screen.getByRole("button", { name: "Hide secret" });

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
  Reflect.deleteProperty(navigator, "clipboard");
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

  // Rewritten by 12f.10.30e (decision 53): it said that no control but "Show secret" requests the secret. Now
  // two do, and only these two: "Show secret", and "Copy URL" while the secret is hidden and a host is set.
  it("test_no_other_control_than_show_secret_and_a_hidden_copy_url_requests_the_secret", async () => {
    stubClipboard();
    const requests: string[] = [];
    const strategy = strategyRoute(ID, "ETH Breakout");
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } }, [], undefined, {}, (url, init) => {
      requests.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith(ORIGIN_PATH)) return Promise.resolve(jsonResponse({ origin: HOST }));
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
    await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
    const secretRequests = () => requests.filter((request) => request.includes("webhook-secret"));

    const others = screen
      .getAllByRole("button")
      .filter((button) => !["Show secret", "Connect a TradingView alert"].includes(button.textContent ?? ""))
      .filter((button) => button !== copyUrl());
    expect(others.length).toBeGreaterThan(2);
    for (const button of others) {
      fireEvent.click(button);
      fireEvent.keyDown(document.body, { key: "Escape" });
    }
    fireEvent.click(screen.getByLabelText("Webhook URL"));
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

    // The hidden "Copy URL" is the one other control that asks, and it shows nothing of what it got.
    await press(copyUrl());

    expect(secretRequests()).toHaveLength(1);
    expect(document.body.textContent).not.toContain(SECRET);

    fireEvent.click(screen.getByRole("button", { name: "Show secret" }));
    await waitFor(() => expect(urlText()).toBe(`${HOST}${URL_BASE}${SECRET}`));

    expect(secretRequests()).toHaveLength(2);
    expect(secretRequests().every((request) => request.startsWith("GET "))).toBe(true);
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
      if (String(input).endsWith(ORIGIN_PATH)) return Promise.resolve(jsonResponse({ origin: null }));
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
    expect(secretEntries(queryClient)).toHaveLength(1);

    fireEvent.click(screen.getByRole("link", { name: "leave" }));

    expect(screen.queryByText(`${URL_BASE}${SECRET}`)).not.toBeInTheDocument();
    expect(secretEntries(queryClient)).toHaveLength(0);
    expect(queryClient.getQueryData(["webhook-secret"])).toBeUndefined();

    fireEvent.click(screen.getByRole("link", { name: "return" }));

    expect(screen.getByText(PLACEHOLDER_URL)).toBeInTheDocument();
    expect(calls).toHaveLength(1);

    // Unmounting the whole tree (a closed tab, a route outside this router) evicts it too.
    fireEvent.click(screen.getByRole("button", { name: "Show secret" }));
    await revealedUrl();
    expect(secretEntries(queryClient)).toHaveLength(1);
    view.unmount();
    expect(secretEntries(queryClient)).toHaveLength(0);
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
    await waitFor(() => expect(secretEntries(queryClient)).toHaveLength(1));

    unmount();
    await act(async () => {
      resolveAnswer(jsonResponse({ secret: SECRET }));
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

    expect(secretEntries(queryClient)).toHaveLength(0);
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
    // Rewritten by 12f.10.30e: "Copy URL" needs a host now, and a copy made while the secret is hidden asks for it.
    const writeText = stubClipboard();
    const { queryClient, calls } = setupHost(originAnswers(HOST));
    await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
    // A copy made while the secret is hidden puts the secret on the clipboard, and nowhere else.
    await press(copyUrl());
    fireEvent.click(showButton());
    await waitFor(() => expect(urlText()).toBe(`${HOST}${URL_BASE}${SECRET}`));
    fireEvent.click(screen.getByRole("button", { name: "Hide secret" }));
    fireEvent.click(showButton());
    await waitFor(() => expect(urlText()).toBe(`${HOST}${URL_BASE}${SECRET}`));
    await press(copyUrl());
    await press(copyMessage());
    expect(writeText).toHaveBeenCalledTimes(3);
    expect(JSON.stringify(writeText.mock.calls[0])).toContain(SECRET);
    expect(JSON.stringify(writeText.mock.calls[1])).toContain(SECRET);

    for (const spy of consoleSpies) expect(JSON.stringify(spy.mock.calls)).not.toContain(SECRET);
    expect(JSON.stringify({ ...window.localStorage })).not.toContain(SECRET);
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain(SECRET);
    expect(JSON.stringify(queryClient.getQueryCache().findAll().map((query) => query.queryKey))).not.toContain(SECRET);
    expect(calls.every((call) => !call.url.includes(SECRET))).toBe(true);
  });

  describe("the host of the URL", () => {
    it("test_a_configured_host_is_shown_in_front_of_the_path_and_no_sentence_about_a_missing_host_shows", async () => {
      setupHost(originAnswers(HOST));

      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      expect(screen.queryByText(HOST_UNSET)).toBeNull();
      expect(screen.queryByText(HOST_ERROR)).toBeNull();
    });

    it("test_a_revealed_secret_goes_after_the_host_percent_encoded", async () => {
      setupHost(originAnswers(HOST), answersWith("a&b+c d=e"));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      fireEvent.click(showButton());

      await waitFor(() => expect(urlText()).toBe(`${HOST}${URL_BASE}a%26b%2Bc%20d%3De`));
    });

    it("test_while_the_host_loads_the_path_alone_is_shown", async () => {
      setupHost(() => new Promise<Response>(() => undefined));
      await settle();

      expect(urlText()).toBe(PLACEHOLDER_URL);
      expect(screen.queryByText(HOST_UNSET)).toBeNull();
      expect(screen.queryByText(HOST_ERROR)).toBeNull();
    });

    it('test_origin_null_shows_the_path_alone_and_says_no_public_host_is_configured', async () => {
      setupHost(originAnswers(null));

      await waitFor(() => expect(screen.queryByText(HOST_UNSET)).toBeInTheDocument());

      expect(urlText()).toBe(PLACEHOLDER_URL);
      expect(screen.queryByText(HOST_ERROR)).toBeNull();
    });

    it.each([
      ["a 500", () => Promise.resolve(jsonResponse({ detail: "boom" }, 500))],
      ["a 404 from an older API", () => Promise.resolve(jsonResponse({ detail: "Not Found" }, 404))],
      ["a network failure", () => Promise.reject(new TypeError("offline"))],
      ["a body without an origin", () => Promise.resolve(jsonResponse({ other: HOST }))],
      ["an origin with a path", originAnswers(`${HOST}/hook`)],
      ["an origin with a trailing slash", originAnswers(`${HOST}/`)],
      ["an origin in upper case", originAnswers("HTTPS://Example.ORG")],
    ] as Array<[string, Answer]>)(
      "test_%s_shows_the_path_alone_and_says_the_host_could_not_be_loaded",
      async (_name, origin) => {
        setupHost(origin);

        await waitFor(() => expect(screen.queryByText(HOST_ERROR)).toBeInTheDocument());

        expect(urlText()).toBe(PLACEHOLDER_URL);
        expect(screen.queryByText(HOST_UNSET)).toBeNull();
      },
    );

    it("test_the_url_is_text_never_inside_an_anchor_and_no_request_starts_with_the_origin", async () => {
      const { calls } = setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      const code = screen.getByLabelText("Webhook URL");
      fireEvent.click(code);
      fireEvent.click(showButton());
      await waitFor(() => expect(urlText()).toBe(`${HOST}${URL_BASE}${SECRET}`));
      await settle();

      expect(code.tagName).toBe("CODE");
      expect(code.closest("a")).toBeNull();
      expect(document.querySelector("a, form, [href], [action]")).toBeNull();
      expect(calls.filter((call) => call.url.includes("example.duckdns.org"))).toEqual([]);
      expect(calls.map((call) => call.url).every((url) => url.endsWith(ORIGIN_PATH) || url.endsWith(SECRET_PATH))).toBe(true);
    });

    it("test_the_origin_is_read_when_the_block_is_opened_and_not_before", async () => {
      const requests: string[] = [];
      const strategy = strategyRoute(ID, "ETH Breakout");
      stubApi({ kind: "ok", body: { status: "ok", dry_run: true } }, [], undefined, {}, (url, init) => {
        requests.push(url);
        if (url.endsWith(ORIGIN_PATH)) return Promise.resolve(jsonResponse({ origin: HOST }));
        return strategy(url, init);
      });
      renderAt(
        <Routes>
          <Route path="strategies/:strategyId" element={<StrategyDetailPage />} />
        </Routes>,
        `/strategies/${ID}`,
      );
      await screen.findByRole("heading", { level: 1, name: "ETH Breakout" });
      await settle();
      const originRequests = () => requests.filter((url) => url.endsWith(ORIGIN_PATH));

      expect(originRequests()).toHaveLength(0);

      fireEvent.click(screen.getByRole("button", { name: "Connect a TradingView alert" }));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      expect(originRequests()).toHaveLength(1);
    });
  });

  describe("the Copy buttons", () => {
    it("test_copy_url_sits_beside_show_secret_and_copy_message_under_the_alert_message", async () => {
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      const row = showButton().parentElement as HTMLElement;
      expect(copyUrl().parentElement).toBe(row);
      expect(row).toContainElement(screen.getByLabelText("Webhook URL"));
      const message = screen.getByRole("group", { name: "Alert message" });
      expect(message.parentElement).toContainElement(copyMessage());
      expect(message.compareDocumentPosition(copyMessage()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(row).not.toContainElement(copyMessage());
      // Each button has its own status region, empty until something is copied.
      expect(statusBeside(copyUrl())).toBeEmptyDOMElement();
      expect(statusBeside(copyMessage())).toBeEmptyDOMElement();
      expect(statusBeside(copyUrl())).not.toBe(statusBeside(copyMessage()));
    });

    // Rewritten by 12f.10.30e (decision 53). It said that a copy equals the text of the code element, hidden
    // and revealed. That holds only while the secret is revealed; hidden, the copy is the working URL.
    it("test_the_copied_text_equals_the_text_of_the_code_element_while_the_secret_is_revealed", async () => {
      const writeText = stubClipboard();
      const { calls } = setupHost(originAnswers(HOST), answersWith("a&b+c d=e"));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      fireEvent.click(showButton());
      await waitFor(() => expect(urlText()).toBe(`${HOST}${URL_BASE}a%26b%2Bc%20d%3De`));
      await press(copyUrl());

      expect(writeText).toHaveBeenCalledTimes(1);
      expect(writeText).toHaveBeenLastCalledWith(`${HOST}${URL_BASE}a%26b%2Bc%20d%3De`);
      expect(writeText).toHaveBeenLastCalledWith(urlText());
      // The URL on screen is the real one, so it is copied as it is: the one request is the "Show secret" one.
      expect(secretCallsOf(calls)).toHaveLength(1);
    });

    // Rewritten by 12f.10.30e (decision 53). It said that a copy takes the path alone while there is no host.
    // The path alone does not work in TradingView, so there is nothing to copy: the button is disabled.
    it.each([
      ["a host that is not configured", originAnswers(null)],
      ["a host that could not be loaded", () => Promise.resolve(jsonResponse({ detail: "boom" }, 500))],
      ["a host that is still loading", () => new Promise<Response>(() => undefined)],
    ] as Array<[string, Answer]>)("test_with_%s_copy_url_is_disabled_and_writes_nothing", async (_name, origin) => {
      const writeText = stubClipboard();
      const { calls } = setupHost(origin);
      await settle();

      expect(copyUrl()).toBeDisabled();
      await press(copyUrl());

      expect(writeText).not.toHaveBeenCalled();
      expect(secretCallsOf(calls)).toEqual([]);
      expect(copiedCount()).toBe(0);
      expect(copyMessage()).toBeEnabled();
    });

    it("test_with_a_host_copy_url_is_enabled", async () => {
      setupHost(originAnswers(HOST));

      await waitFor(() => expect(copyUrl()).toBeEnabled());
    });

    it("test_the_message_copied_is_the_message_shown", async () => {
      const writeText = stubClipboard();
      setupHost(originAnswers(HOST));

      await press(copyMessage());

      expect(writeText).toHaveBeenCalledTimes(1);
      expect(writeText).toHaveBeenCalledWith(messageText());
      expect(writeText).toHaveBeenCalledWith(webhookMessage(ID));
    });

    // Rewritten by 12f.10.30e (decision 53). It said that a copy makes no request. Now only "Copy message", and
    // "Copy URL" while the secret is revealed, make none; "Copy URL" while it is hidden makes exactly one.
    it("test_only_a_hidden_copy_url_asks_for_the_secret_and_it_asks_once_per_copy", async () => {
      const writeText = stubClipboard();
      const { calls } = setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      const before = calls.length;

      await press(copyMessage());
      await settle();

      expect(writeText).toHaveBeenCalledTimes(1);
      expect(calls).toHaveLength(before);

      await press(copyUrl());
      await settle();

      expect(writeText).toHaveBeenCalledTimes(2);
      expect(secretCallsOf(calls)).toHaveLength(1);
      expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`);
      expect(document.body.textContent).not.toContain(SECRET);

      // The button reading "Copied" copies again, and asks again: the secret is kept nowhere between copies.
      await press(copyUrl());
      await settle();

      expect(writeText).toHaveBeenCalledTimes(3);
      expect(secretCallsOf(calls)).toHaveLength(2);

      // With the secret revealed, a copy asks for nothing more.
      fireEvent.click(showButton());
      await waitFor(() => expect(urlText()).toBe(`${HOST}${URL_BASE}${SECRET}`));
      const revealed = calls.length;
      await press(copyUrl());
      await press(copyMessage());
      await settle();

      expect(writeText).toHaveBeenCalledTimes(5);
      expect(calls).toHaveLength(revealed);
      expect(secretCallsOf(calls)).toHaveLength(3);
    });

    // Rewritten by 12f.10.30e (decision 53). It said that with the secret hidden the copy is the URL with the
    // placeholder, which does not work in TradingView. It is the URL with the secret, percent-encoded.
    it("test_with_the_secret_hidden_it_copies_the_url_with_the_secret_and_never_the_placeholder", async () => {
      const writeText = stubClipboard();
      const { calls } = setupHost(originAnswers(HOST), answersWith(AWKWARD));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      await press(copyUrl());

      expect(writeText).toHaveBeenCalledTimes(1);
      expect(writeText).toHaveBeenCalledWith(`${HOST}/webhook/tradingview?secret=${AWKWARD_ENCODED}`);
      expect(JSON.stringify(writeText.mock.calls)).not.toContain("WEBHOOK_SECRET");
      expect(secretCallsOf(calls)).toHaveLength(1);
      expect(new Headers(secretCallsOf(calls)[0]?.init?.headers).get("Authorization")).toBe("Bearer test-token");
    });

    it.each([
      ["no clipboard", () => setClipboard(undefined)],
      ["a clipboard without writeText", () => setClipboard({})],
      ["a rejected write", () => setClipboard({ writeText: vi.fn().mockRejectedValue(new DOMException("denied")) })],
    ])("test_%s_shows_could_not_copy_in_the_loss_colour_beside_each_button", async (_name, arrange) => {
      arrange();
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      await press(copyUrl());

      expect(statusBeside(copyUrl())).toHaveTextContent(COPY_FAILED);
      expect(statusBeside(copyUrl())).toHaveClass("text-loss");
      expect(copiedCount()).toBe(0);
      // The failure is a visible text, and the button keeps its ordinary text.
      expect(statusBeside(copyUrl()).className.split(/\s+/)).not.toContain("sr-only");
      expect(copyUrl()).toHaveAccessibleName("Copy URL");

      await press(copyMessage());

      expect(statusBeside(copyMessage())).toHaveTextContent(COPY_FAILED);
      expect(statusBeside(copyMessage())).toHaveClass("text-loss");
      expect(copiedCount()).toBe(0);
      expect(statusBeside(copyMessage()).className.split(/\s+/)).not.toContain("sr-only");
      expect(copyMessage()).toHaveAccessibleName("Copy message");
    });

    // Re-pointed by 12f.10.30d: the button used reads "Copied", and its status region says it, hidden from sight.
    it("test_a_working_copy_makes_the_button_used_read_copied_and_its_status_says_it_unseen", async () => {
      stubClipboard();
      setupHost(originAnswers(HOST));

      await press(copyMessage());

      expect(copyMessage()).toHaveAccessibleName("Copied");
      expect(copyUrl()).toHaveAccessibleName("Copy URL");
      expect(statusBeside(copyMessage())).toHaveTextContent("Copied");
      expect(statusBeside(copyMessage())).not.toHaveClass("text-loss");
      expect(statusBeside(copyMessage()).className.split(/\s+/)).toContain("sr-only");
      expect(statusBeside(copyUrl())).toBeEmptyDOMElement();
    });
  });

  describe("the rule for Copied", () => {
    /** An origin route that stays pending until the test lets it answer, as a slow host does. */
    function lateOrigin() {
      let answer: (origin: string | null) => void = () => undefined;
      const route: Answer = () =>
        new Promise<Response>((resolve) => {
          answer = (origin) => resolve(jsonResponse({ origin }));
        });
      const arrive = (origin: string | null) =>
        act(async () => {
          answer(origin);
          // The answer is parsed, checked and handed to the view over a few ticks.
          await new Promise((resolve) => setTimeout(resolve, 30));
        });
      return { route, arrive };
    }
    // Re-pointed by 12f.10.30d: "Copied" stands in the button's own text, not in a text beside it.
    const copiedBeside = (button: HTMLElement) => screen.queryAllByRole("button", { name: "Copied" }).includes(button);
    const revealed = () => waitFor(() => expect(urlText()).toContain(`${URL_BASE}${SECRET}`));

    it("test_copied_shows_beside_the_button_that_was_used_and_only_one_copied_is_on_screen", async () => {
      stubClipboard();
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      await press(copyUrl());

      expect(copyUrl()).toHaveAccessibleName("Copied");
      expect(copyMessage()).toHaveAccessibleName("Copy message");
      expect(statusBeside(copyUrl())).toHaveTextContent("Copied");
      expect(statusBeside(copyMessage())).toBeEmptyDOMElement();
      expect(copiedCount()).toBe(1);
      expect(announcedCount()).toBe(1);

      await press(copyMessage());

      expect(copyMessage()).toHaveAccessibleName("Copied");
      expect(copyUrl()).toHaveAccessibleName("Copy URL");
      expect(statusBeside(copyMessage())).toHaveTextContent("Copied");
      expect(statusBeside(copyUrl())).toBeEmptyDOMElement();
      expect(copiedCount()).toBe(1);
      expect(announcedCount()).toBe(1);

      await press(copyUrl());

      expect(copyUrl()).toHaveAccessibleName("Copied");
      expect(copyMessage()).toHaveAccessibleName("Copy message");
      expect(statusBeside(copyUrl())).toHaveTextContent("Copied");
      expect(statusBeside(copyMessage())).toBeEmptyDOMElement();
      expect(copiedCount()).toBe(1);
      expect(announcedCount()).toBe(1);
    });

    it("test_closing_the_block_removes_it", async () => {
      stubClipboard();
      // 12f.10.30e: "Copy URL" needs a host, so this deployment names one, and the secret route answers.
      const strategy = strategyRoute(ID, "ETH Breakout");
      stubApi({ kind: "ok", body: { status: "ok", dry_run: true } }, [], undefined, {}, (url, init) => {
        if (url.endsWith(ORIGIN_PATH)) return Promise.resolve(jsonResponse({ origin: HOST }));
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
      const toggle = () => screen.getByRole("button", { name: "Connect a TradingView alert" });
      fireEvent.click(toggle());
      await waitFor(() => expect(copyUrl()).toBeEnabled());
      await press(copyUrl());
      expect(copiedCount()).toBe(1);
      await press(copyMessage());
      expect(copiedCount()).toBe(1);

      fireEvent.click(toggle());

      expect(screen.queryByText("Copied")).toBeNull();
      expect(screen.queryByRole("button", { name: "Copy URL" })).toBeNull();

      fireEvent.click(toggle());

      // Re-pointed by 12f.10.30d: the buttons hold "Copied" as a hidden text, so it is the buttons' names that are read.
      expect(copiedCount()).toBe(0);
      expect(announcedCount()).toBe(0);
      expect(statusBeside(copyUrl())).toBeEmptyDOMElement();
      expect(statusBeside(copyMessage())).toBeEmptyDOMElement();
    });

    // Rewritten by 12f.10.30e (decision 53), together with the next three. They said that showing or hiding the
    // secret takes "Copied" away from "Copy URL", because the clipboard could hold a different URL from the one
    // on screen. It cannot now: the clipboard holds the working URL whether the secret is shown or hidden.
    it("test_the_url_copied_with_the_secret_hidden_then_show_secret_copied_stays", async () => {
      const writeText = stubClipboard();
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      await press(copyUrl());
      expect(statusBeside(copyUrl())).toHaveTextContent("Copied");
      expect(copyUrl()).toHaveAccessibleName("Copied");

      fireEvent.click(showButton());
      await revealed();

      expect(statusBeside(copyUrl())).toHaveTextContent("Copied");
      expect(copyUrl()).toHaveAccessibleName("Copied");
      expect(copiedCount()).toBe(1);
      // The clipboard holds the URL the screen now shows.
      expect(writeText).toHaveBeenLastCalledWith(urlText());
    });

    it("test_the_url_copied_revealed_then_hide_secret_copied_stays", async () => {
      const writeText = stubClipboard();
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      fireEvent.click(showButton());
      await revealed();
      await press(copyUrl());
      expect(statusBeside(copyUrl())).toHaveTextContent("Copied");
      expect(copyUrl()).toHaveAccessibleName("Copied");

      fireEvent.click(hideButton());

      expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`);
      expect(statusBeside(copyUrl())).toHaveTextContent("Copied");
      expect(copyUrl()).toHaveAccessibleName("Copied");
      expect(writeText).toHaveBeenLastCalledWith(`${HOST}${URL_BASE}${SECRET}`);
    });

    it("test_showing_and_hiding_the_secret_again_leaves_copied_where_it_was", async () => {
      stubClipboard();
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      await press(copyUrl());
      fireEvent.click(showButton());
      await revealed();
      expect(copiedCount()).toBe(1);

      fireEvent.click(hideButton());
      expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`);
      expect(copiedCount()).toBe(1);

      fireEvent.click(showButton());
      await revealed();
      expect(copiedCount()).toBe(1);
      expect(copyUrl()).toHaveAccessibleName("Copied");
    });

    // Rewritten by 12f.10.30e: the old name was "test_hiding_the_secret_and_showing_it_again_does_not_bring_back_a_copy_of_the_revealed_url".
    it("test_a_copy_made_revealed_stays_copied_through_hide_and_show_again", async () => {
      stubClipboard();
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      fireEvent.click(showButton());
      await revealed();
      await press(copyUrl());
      expect(copyUrl()).toHaveAccessibleName("Copied");

      fireEvent.click(hideButton());
      fireEvent.click(showButton());
      await revealed();

      expect(urlText()).toBe(`${HOST}${URL_BASE}${SECRET}`);
      expect(copyUrl()).toHaveAccessibleName("Copied");
      expect(copiedCount()).toBe(1);
    });

    it("test_a_show_that_fails_leaves_copied_on_copy_url", async () => {
      stubClipboard();
      let answers = 0;
      setupHost(originAnswers(HOST), () => {
        answers += 1;
        return answers === 1 ? Promise.resolve(jsonResponse({ secret: SECRET })) : Promise.resolve(jsonResponse({ detail: "not configured" }, 503));
      });
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      await press(copyUrl());
      expect(statusBeside(copyUrl())).toHaveTextContent("Copied");
      expect(copyUrl()).toHaveAccessibleName("Copied");

      fireEvent.click(showButton());
      await screen.findByRole("alert");

      expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`);
      expect(statusBeside(copyUrl())).toHaveTextContent("Copied");
      expect(copyUrl()).toHaveAccessibleName("Copied");
    });

    it("test_the_url_copied_then_the_other_button_used_copied_moves_to_it", async () => {
      stubClipboard();
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      await press(copyUrl());
      expect(copyUrl()).toHaveAccessibleName("Copied");

      await press(copyMessage());

      expect(copyMessage()).toHaveAccessibleName("Copied");
      expect(copyUrl()).toHaveAccessibleName("Copy URL");
      expect(copiedCount()).toBe(1);
    });

    // The host cannot change by a handler: it changes when the host's own read answers again. "Copied" then
    // stands only if the host on screen is the one that was copied.
    it("test_the_url_copied_then_the_host_on_screen_changes_copied_is_gone", async () => {
      const writeText = stubClipboard();
      let origin: string = HOST;
      const { queryClient } = setupHost(() => Promise.resolve(jsonResponse({ origin })));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      await press(copyUrl());
      expect(copyUrl()).toHaveAccessibleName("Copied");
      expect(writeText).toHaveBeenLastCalledWith(`${HOST}${URL_BASE}${SECRET}`);

      origin = "https://other.example.org";
      await act(async () => {
        await queryClient.invalidateQueries({ queryKey: ["webhook-origin"] });
      });

      expect(urlText()).toBe(`https://other.example.org${PLACEHOLDER_URL}`);
      expect(statusBeside(copyUrl())).toBeEmptyDOMElement();
      expect(copyUrl()).toHaveAccessibleName("Copy URL");
      expect(copiedCount()).toBe(0);
    });

    it("test_the_url_copied_then_the_same_host_is_read_again_copied_stays", async () => {
      stubClipboard();
      const { queryClient } = setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      await press(copyUrl());

      await act(async () => {
        await queryClient.invalidateQueries({ queryKey: ["webhook-origin"] });
      });

      expect(copyUrl()).toHaveAccessibleName("Copied");
      expect(copiedCount()).toBe(1);
    });

    it("test_the_messages_copied_survives_showing_and_hiding_the_secret", async () => {
      stubClipboard();
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      await press(copyMessage());

      fireEvent.click(showButton());
      await revealed();
      expect(statusBeside(copyMessage())).toHaveTextContent("Copied");
      expect(copyMessage()).toHaveAccessibleName("Copied");

      fireEvent.click(hideButton());
      expect(statusBeside(copyMessage())).toHaveTextContent("Copied");
      expect(copyMessage()).toHaveAccessibleName("Copied");
      expect(copiedCount()).toBe(1);
    });

    // Rewritten by 12f.10.30e (decision 53). It said that the clipboard never holds something the screen does not
    // show next to "Copied". Now it never holds the placeholder, and whenever "Copied" stands on "Copy URL" the
    // clipboard holds the working URL: the host on screen and the secret the server holds, percent-encoded.
    it("test_the_clipboard_never_holds_the_placeholder_and_holds_the_working_url_next_to_copied", async () => {
      const writeText = stubClipboard();
      const host = lateOrigin();
      setupHost(host.route, answersWith(AWKWARD));
      const working = `${HOST}${URL_BASE}${AWKWARD_ENCODED}`;
      /** Whatever has been written so far, for either button, is a real text and never the placeholder. */
      const check = () => {
        for (const [text] of writeText.mock.calls) expect(String(text)).not.toContain("WEBHOOK_SECRET");
        if (copiedBeside(copyUrl())) expect(writeText).toHaveBeenLastCalledWith(working);
        if (copiedBeside(copyMessage())) expect(writeText).toHaveBeenLastCalledWith(messageText());
      };

      await press(copyUrl());
      check();
      expect(writeText).not.toHaveBeenCalled();
      await press(copyMessage());
      check();
      await host.arrive(HOST);
      check();
      await press(copyUrl());
      check();
      expect(copiedBeside(copyUrl())).toBe(true);
      fireEvent.click(showButton());
      await waitFor(() => expect(urlText()).toBe(working));
      check();
      expect(copiedBeside(copyUrl())).toBe(true);
      await press(copyUrl());
      check();
      fireEvent.click(hideButton());
      check();
      expect(copiedBeside(copyUrl())).toBe(true);
      await press(copyUrl());
      check();
      expect(copiedBeside(copyUrl())).toBe(true);
      expect(copiedBeside(copyMessage())).toBe(false);
      expect(writeText).toHaveBeenCalledTimes(4);
    });
  });

  /**
   * The six new texts of design § I, in both languages, held here and not read from the locale files, so a
   * reworded value is red. Each Spanish text is required by name: an untranslated value equals its English twin.
   */
  describe.each([
    {
      language: "en",
      copyUrl: "Copy URL",
      copyMessage: "Copy message",
      copied: "Copied",
      copyFailed: "Could not copy. Select the text and copy it by hand.",
      hostUnset:
        "No public host is configured for the webhook, so only the path is shown. Put your webhook's host in front of it.",
      hostError: "The webhook's host could not be loaded, so only the path is shown.",
    },
    {
      language: "es",
      copyUrl: "Copiar URL",
      copyMessage: "Copiar mensaje",
      copied: "Copiado",
      copyFailed: "No se pudo copiar. Seleccione el texto y cópielo a mano.",
      hostUnset:
        "No hay un host público configurado para el webhook, por lo que solo se muestra la ruta. Anteponga el host de su webhook.",
      hostError: "No se pudo cargar el host del webhook, por lo que solo se muestra la ruta.",
    },
  ])("the six new texts in $language", (T) => {
    beforeEach(async () => {
      await act(() => i18n.changeLanguage(T.language));
    });

    // Re-pointed by 12f.10.30d: after a copy the button's name is Copied, so it is found by place.
    it("the two buttons' names and Copied, as the button's text and in the status beside the button used", async () => {
      stubClipboard();
      // 12f.10.30e: "Copy URL" is disabled with no host, so the copy is made with one.
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(copyUrl()).toBeEnabled());

      await press(screen.getByRole("button", { name: T.copyUrl }));
      expect(copyUrl()).toHaveAccessibleName(T.copied);
      expect(statusBeside(copyUrl())).toHaveTextContent(T.copied);
      await press(screen.getByRole("button", { name: T.copyMessage }));
      expect(copyMessage()).toHaveAccessibleName(T.copied);
      expect(statusBeside(copyMessage())).toHaveTextContent(T.copied);
      expect(copyUrl()).toHaveAccessibleName(T.copyUrl);
    });

    it("the refusal of a copy, in the loss colour", async () => {
      setClipboard(undefined);
      // 12f.10.30e: "Copy URL" is disabled with no host, so the refused copy is made with one.
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(copyUrl()).toBeEnabled());

      await press(screen.getByRole("button", { name: T.copyUrl }));

      const status = statusBeside(screen.getByRole("button", { name: T.copyUrl }));
      expect(status).toHaveTextContent(T.copyFailed);
      expect(status).toHaveClass("text-loss");
    });

    it("the sentence for a host that is not configured, and for one that could not be loaded", async () => {
      setupHost(originAnswers(null));
      await waitFor(() => expect(screen.queryByText(T.hostUnset)).toBeInTheDocument());
      cleanup();

      setupHost(() => Promise.resolve(jsonResponse({ detail: "Not Found" }, 404)));
      await waitFor(() => expect(screen.queryByText(T.hostError)).toBeInTheDocument());
    });
  });

  it("renders its texts in Spanish", async () => {
    await i18n.changeLanguage("es");
    setup();

    expect(screen.getByRole("button", { name: "Mostrar el secreto" })).toBeInTheDocument();
    expect(screen.getByText(`${URL_BASE}<su WEBHOOK_SECRET>`)).toBeInTheDocument();
  });
});

// 12f.10.30d. jsdom has no layout, so the width rule is pinned by structure: both texts of a Copy button are
// in the button, in one cell, and the one not shown is hidden from sight and from assistive technology.
describe.each([
  { language: "en", copyUrl: "Copy URL", copyMessage: "Copy message", copied: "Copied" },
  { language: "es", copyUrl: "Copiar URL", copyMessage: "Copiar mensaje", copied: "Copiado" },
] as const)("WebhookMessage, Copied is the button's own text, in $language (12f.10.30d)", (T) => {
  beforeEach(async () => {
    await act(() => i18n.changeLanguage(T.language));
  });

  const classesOf = (element: Element) => element.className.split(/\s+/);
  const cellOf = (host: HTMLElement, text: string) => within(host).getByText(text);
  const isShown = (cell: HTMLElement) => !cell.hasAttribute("aria-hidden") && !classesOf(cell).includes("invisible");
  const isHidden = (cell: HTMLElement) =>
    cell.getAttribute("aria-hidden") === "true" && classesOf(cell).includes("invisible");
  /** Every element that holds exactly `text`, outside the buttons. */
  const outsideButtons = (text: string) => screen.queryAllByText(text).filter((node) => node.closest("button") === null);

  it("each Copy button holds its text and Copied, and shows only its own text while nothing was copied", async () => {
    setupHost(originAnswers(null));
    await settle();

    for (const [button, text] of [
      [copyUrl(), T.copyUrl],
      [copyMessage(), T.copyMessage],
    ] as const) {
      expect(isShown(cellOf(button, text))).toBe(true);
      expect(isHidden(cellOf(button, T.copied))).toBe(true);
    }
  });

  it.each([
    ["Copy URL", copyUrl, "copyUrl"],
    ["Copy message", copyMessage, "copyMessage"],
  ] as const)("%s reads Copied after a copy, stays enabled, and shows only that one of its two texts", async (_name, find, key) => {
    stubClipboard();
    // 12f.10.30e: "Copy URL" is disabled with no host, so both copies are made with one.
    setupHost(originAnswers(HOST));
    await waitFor(() => expect(copyUrl()).toBeEnabled());

    await press(find());

    const button = screen.getByRole("button", { name: T.copied });
    expect(button).toBe(find());
    expect(button).toBeEnabled();
    expect(isShown(cellOf(button, T.copied))).toBe(true);
    expect(isHidden(cellOf(button, T[key]))).toBe(true);
    expect(screen.queryAllByRole("button", { name: T.copied })).toHaveLength(1);
  });

  it("leaves no visible Copied beside the button: the one text outside the buttons is the hidden status", async () => {
    stubClipboard();
    setupHost(originAnswers(null));
    await settle();
    await press(copyMessage());

    const elsewhere = outsideButtons(T.copied);

    expect(elsewhere).toHaveLength(1);
    const status = elsewhere[0] as HTMLElement;
    expect(status).toHaveAttribute("role", "status");
    expect(classesOf(status)).toContain("sr-only");
    expect(copyMessage().parentElement).toContainElement(status);
  });

  it("a button that reads Copied copies again when pressed, and still reads Copied", async () => {
    const writeText = stubClipboard();
    // 12f.10.30e: "Copy URL" is disabled with no host, so the copy is made with one.
    setupHost(originAnswers(HOST));
    await waitFor(() => expect(copyUrl()).toBeEnabled());
    await press(copyUrl());

    await press(screen.getByRole("button", { name: T.copied }));

    expect(writeText).toHaveBeenCalledTimes(2);
    expect(copyUrl()).toHaveAccessibleName(T.copied);
    expect(screen.queryAllByRole("button", { name: T.copied })).toHaveLength(1);
  });

  it("a copy that failed leaves the button's ordinary text and says so in a visible text", async () => {
    setClipboard(undefined);
    // 12f.10.30e: "Copy URL" is disabled with no host, so the failed copy is made with one.
    setupHost(originAnswers(HOST));
    await waitFor(() => expect(copyUrl()).toBeEnabled());

    await press(copyUrl());

    expect(copyUrl()).toHaveAccessibleName(T.copyUrl);
    expect(screen.queryAllByRole("button", { name: T.copied })).toHaveLength(0);
    const failure = statusBeside(copyUrl());
    expect(failure).not.toBeEmptyDOMElement();
    expect(classesOf(failure)).toContain("text-loss");
    expect(classesOf(failure)).not.toContain("sr-only");
  });
});

// 12f.10.30e (decision 53). With the secret hidden, "Copy URL" asks the server for it at the click, writes the
// URL that works, and keeps the secret in a local value of that one click: on screen, in the cache, in the DOM,
// in the console and in storage there is nothing of it afterwards.
describe("WebhookMessage, Copy URL copies the working URL while the secret is hidden (12f.10.30e)", () => {
  const WORKING = `${HOST}${URL_BASE}${AWKWARD_ENCODED}`;
  /** Every place a leak could be read from, other than the clipboard. */
  const leaksOf = (queryClient: QueryClient): string[] => {
    const places = [
      document.body.innerHTML,
      document.body.textContent ?? "",
      JSON.stringify(queryClient.getQueryCache().findAll().map((query) => [query.queryKey, query.state.data])),
      JSON.stringify({ ...window.localStorage }),
      JSON.stringify({ ...window.sessionStorage }),
      ...consoleSpies.map((spy) => JSON.stringify(spy.mock.calls)),
    ];
    return places.filter((place) =>
      [AWKWARD, AWKWARD_ENCODED, "p&amp;q", "p%26q"].some((form) => place.includes(form)),
    );
  };

  it("writes the URL with the secret, and the screen, the button and Show secret stay as they were", async () => {
    const writeText = stubClipboard();
    const { queryClient } = setupHost(originAnswers(HOST), answersWith(AWKWARD));
    await waitFor(() => expect(copyUrl()).toBeEnabled());

    await press(copyUrl());

    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith(WORKING);
    expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`);
    expect(showButton()).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Hide secret" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(copyUrl()).toHaveAccessibleName("Copied");
    expect(leaksOf(queryClient)).toEqual([]);
  });

  it("leaves the query cache without the secret, and a later Show secret makes its own request", async () => {
    const writeText = stubClipboard();
    const { queryClient, calls } = setupHost(originAnswers(HOST), answersWith(AWKWARD));
    await waitFor(() => expect(copyUrl()).toBeEnabled());

    await press(copyUrl());
    await settle();

    expect(writeText).toHaveBeenCalledWith(WORKING);
    expect(queryClient.getQueryData(["webhook-secret"])).toBeUndefined();
    expect(cachedData(queryClient).filter((data) => data !== undefined)).toEqual([]);

    fireEvent.click(showButton());
    await waitFor(() => expect(urlText()).toBe(WORKING));

    expect(secretCallsOf(calls)).toHaveLength(2);
  });

  it.each([
    ["a network failure", () => Promise.reject(new TypeError("offline"))],
    ["a refusal of the token", () => Promise.resolve(jsonResponse({ detail: "unauthorized" }, 401))],
    ["a server error", () => Promise.resolve(jsonResponse({ detail: "the webhook secret is not configured" }, 503))],
    ["an empty secret", () => Promise.resolve(jsonResponse({ secret: "" }))],
    ["a body that is not a secret", () => Promise.resolve(jsonResponse({ other: "leaked-value-123" }))],
  ] as Array<[string, Answer]>)(
    "test_%s_writes_nothing_and_says_could_not_copy",
    async (_name, secret) => {
      const writeText = stubClipboard();
      const { calls, queryClient } = setupHost(originAnswers(HOST), secret);
      await waitFor(() => expect(copyUrl()).toBeEnabled());

      await press(copyUrl());
      await settle();

      expect(secretCallsOf(calls)).toHaveLength(1);
      expect(writeText).not.toHaveBeenCalled();
      expect(statusBeside(copyUrl())).toHaveTextContent(COPY_FAILED);
      expect(statusBeside(copyUrl())).toHaveClass("text-loss");
      expect(copyUrl()).toHaveAccessibleName("Copy URL");
      expect(copiedCount()).toBe(0);
      expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`);
      expect(document.body.textContent).not.toContain("leaked-value-123");
      expect(queryClient.getQueryData(["webhook-secret"])).toBeUndefined();
    },
  );

  it("a failed request does not stop the next click, which copies the working URL", async () => {
    const writeText = stubClipboard();
    let attempt = 0;
    const { calls } = setupHost(originAnswers(HOST), () => {
      attempt += 1;
      return attempt === 1 ? Promise.reject(new TypeError("offline")) : Promise.resolve(jsonResponse({ secret: AWKWARD }));
    });
    await waitFor(() => expect(copyUrl()).toBeEnabled());
    await press(copyUrl());
    await settle();
    expect(statusBeside(copyUrl())).toHaveTextContent(COPY_FAILED);
    expect(writeText).not.toHaveBeenCalled();

    await press(copyUrl());

    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith(WORKING);
    expect(copyUrl()).toHaveAccessibleName("Copied");
    expect(statusBeside(copyUrl())).not.toHaveTextContent(COPY_FAILED);
    expect(secretCallsOf(calls)).toHaveLength(2);
  });

  it("a write the browser refuses after the request says could not copy and leaves the secret nowhere", async () => {
    const refuse = vi.fn().mockRejectedValue(new DOMException("denied"));
    setClipboard({ writeText: refuse });
    const { calls, queryClient } = setupHost(originAnswers(HOST), answersWith(AWKWARD));
    await waitFor(() => expect(copyUrl()).toBeEnabled());

    await press(copyUrl());

    expect(secretCallsOf(calls)).toHaveLength(1);
    expect(refuse).toHaveBeenCalledWith(WORKING);
    expect(statusBeside(copyUrl())).toHaveTextContent(COPY_FAILED);
    expect(copyUrl()).toHaveAccessibleName("Copy URL");
    expect(copiedCount()).toBe(0);
    expect(leaksOf(queryClient)).toEqual([]);
  });

  it("is disabled while the request is in flight, sends no second request, and keeps its text", async () => {
    const writeText = stubClipboard();
    let answer: (response: Response) => void = () => undefined;
    const { calls } = setupHost(
      originAnswers(HOST),
      () => new Promise<Response>((resolve) => (answer = resolve)),
    );
    await waitFor(() => expect(copyUrl()).toBeEnabled());

    await press(copyUrl());
    await settle();

    expect(secretCallsOf(calls)).toHaveLength(1);
    expect(copyUrl()).toBeDisabled();
    expect(copyUrl()).toHaveAccessibleName("Copy URL");
    expect(copyMessage()).toBeEnabled();

    await press(copyUrl());
    await settle();

    expect(secretCallsOf(calls)).toHaveLength(1);
    expect(writeText).not.toHaveBeenCalled();

    await act(async () => {
      answer(jsonResponse({ secret: AWKWARD }));
      await new Promise((resolve) => setTimeout(resolve, 30));
    });

    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith(WORKING);
    expect(copyUrl()).toBeEnabled();
    expect(copyUrl()).toHaveAccessibleName("Copied");
  });

  it("is enabled again after a request that failed", async () => {
    stubClipboard();
    setupHost(originAnswers(HOST), () => Promise.resolve(jsonResponse({ detail: "boom" }, 500)));
    await waitFor(() => expect(copyUrl()).toBeEnabled());

    await press(copyUrl());
    await settle();

    expect(copyUrl()).toBeEnabled();
  });

  it("copies the URL on screen as it is, with no request, once the secret is shown", async () => {
    const writeText = stubClipboard();
    const { calls } = setupHost(originAnswers(HOST), answersWith(AWKWARD));
    await waitFor(() => expect(copyUrl()).toBeEnabled());
    fireEvent.click(showButton());
    await waitFor(() => expect(urlText()).toBe(WORKING));
    expect(secretCallsOf(calls)).toHaveLength(1);

    await press(copyUrl());
    await settle();

    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith(WORKING);
    expect(secretCallsOf(calls)).toHaveLength(1);
  });

  it("after Hide, a hidden copy asks again and leaves nothing of the secret behind", async () => {
    const writeText = stubClipboard();
    const { calls, queryClient } = setupHost(originAnswers(HOST), answersWith(AWKWARD));
    await waitFor(() => expect(copyUrl()).toBeEnabled());
    fireEvent.click(showButton());
    await waitFor(() => expect(urlText()).toBe(WORKING));
    fireEvent.click(hideButton());

    await press(copyUrl());
    await settle();

    expect(secretCallsOf(calls)).toHaveLength(2);
    expect(writeText).toHaveBeenCalledWith(WORKING);
    expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`);
    expect(leaksOf(queryClient)).toEqual([]);
  });
});
