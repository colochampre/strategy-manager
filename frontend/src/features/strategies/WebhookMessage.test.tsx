import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

const copyUrl = () => screen.getByRole("button", { name: "Copy URL" });
const copyMessage = () => screen.getByRole("button", { name: "Copy message" });
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
    const { queryClient, calls } = setup();
    fireEvent.click(showButton());
    await revealedUrl();
    fireEvent.click(screen.getByRole("button", { name: "Hide secret" }));
    fireEvent.click(showButton());
    await revealedUrl();
    // A copy of the revealed URL puts the secret on the clipboard, and nowhere else.
    const writeText = stubClipboard();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy URL" }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy message" }));
    });
    expect(writeText).toHaveBeenCalledTimes(2);
    expect(JSON.stringify(writeText.mock.calls[0])).toContain(SECRET);

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

    it("test_the_copied_text_equals_the_text_of_the_code_element_hidden_and_revealed", async () => {
      const writeText = stubClipboard();
      setupHost(originAnswers(HOST), answersWith("a&b+c d=e"));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      await press(copyUrl());

      expect(writeText).toHaveBeenCalledTimes(1);
      expect(writeText).toHaveBeenLastCalledWith(urlText());

      fireEvent.click(showButton());
      await waitFor(() => expect(urlText()).toBe(`${HOST}${URL_BASE}a%26b%2Bc%20d%3De`));
      await press(copyUrl());

      expect(writeText).toHaveBeenCalledTimes(2);
      expect(writeText).toHaveBeenLastCalledWith(`${HOST}${URL_BASE}a%26b%2Bc%20d%3De`);
      expect(writeText).toHaveBeenLastCalledWith(urlText());
    });

    it("test_the_path_alone_is_what_a_copy_takes_while_there_is_no_host", async () => {
      const writeText = stubClipboard();
      setupHost(originAnswers(null));
      await waitFor(() => expect(screen.queryByText(HOST_UNSET)).toBeInTheDocument());

      await press(copyUrl());

      expect(writeText).toHaveBeenCalledWith(PLACEHOLDER_URL);
    });

    it("test_the_message_copied_is_the_message_shown", async () => {
      const writeText = stubClipboard();
      setupHost(originAnswers(HOST));

      await press(copyMessage());

      expect(writeText).toHaveBeenCalledTimes(1);
      expect(writeText).toHaveBeenCalledWith(messageText());
      expect(writeText).toHaveBeenCalledWith(webhookMessage(ID));
    });

    it("test_a_copy_makes_no_request_and_never_asks_for_the_secret", async () => {
      const writeText = stubClipboard();
      const { calls } = setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      const before = calls.length;

      await press(copyUrl());
      await press(copyMessage());
      await settle();

      expect(writeText).toHaveBeenCalledTimes(2);
      expect(calls).toHaveLength(before);
      expect(secretCallsOf(calls)).toEqual([]);
      expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`);
      expect(document.body.textContent).not.toContain(SECRET);

      // With the secret revealed, a copy still asks for nothing more.
      fireEvent.click(showButton());
      await waitFor(() => expect(urlText()).toBe(`${HOST}${URL_BASE}${SECRET}`));
      const revealed = calls.length;
      await press(copyUrl());
      await press(copyMessage());
      await settle();

      expect(writeText).toHaveBeenCalledTimes(4);
      expect(calls).toHaveLength(revealed);
      expect(secretCallsOf(calls)).toHaveLength(1);
    });

    it("test_with_the_secret_hidden_it_copies_the_url_with_the_placeholder", async () => {
      const writeText = stubClipboard();
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      await press(copyUrl());

      expect(writeText).toHaveBeenCalledWith(`${HOST}/webhook/tradingview?secret=<your WEBHOOK_SECRET>`);
      expect(JSON.stringify(writeText.mock.calls)).not.toContain(SECRET);
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
      expect(screen.queryByText("Copied")).toBeNull();

      await press(copyMessage());

      expect(statusBeside(copyMessage())).toHaveTextContent(COPY_FAILED);
      expect(statusBeside(copyMessage())).toHaveClass("text-loss");
      expect(screen.queryByText("Copied")).toBeNull();
    });

    it("test_a_working_copy_says_copied_beside_the_button_used_and_in_neutral_ink", async () => {
      stubClipboard();
      setupHost(originAnswers(HOST));

      await press(copyMessage());

      expect(statusBeside(copyMessage())).toHaveTextContent("Copied");
      expect(statusBeside(copyMessage())).not.toHaveClass("text-loss");
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
    const copiedBeside = (button: HTMLElement) => statusBeside(button).textContent === "Copied";
    const copiedCount = () => screen.queryAllByText("Copied").length;
    const revealed = () => waitFor(() => expect(urlText()).toContain(`${URL_BASE}${SECRET}`));

    it("test_copied_shows_beside_the_button_that_was_used_and_only_one_copied_is_on_screen", async () => {
      stubClipboard();
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      await press(copyUrl());

      expect(statusBeside(copyUrl())).toHaveTextContent("Copied");
      expect(statusBeside(copyMessage())).toBeEmptyDOMElement();
      expect(copiedCount()).toBe(1);

      await press(copyMessage());

      expect(statusBeside(copyMessage())).toHaveTextContent("Copied");
      expect(statusBeside(copyUrl())).toBeEmptyDOMElement();
      expect(copiedCount()).toBe(1);

      await press(copyUrl());

      expect(statusBeside(copyUrl())).toHaveTextContent("Copied");
      expect(statusBeside(copyMessage())).toBeEmptyDOMElement();
      expect(copiedCount()).toBe(1);
    });

    it("test_closing_the_block_removes_it", async () => {
      stubClipboard();
      stubApi({ kind: "ok", body: { status: "ok", dry_run: true } }, [], undefined, {}, strategyRoute(ID, "ETH Breakout"));
      renderAt(
        <Routes>
          <Route path="strategies/:strategyId" element={<StrategyDetailPage />} />
        </Routes>,
        `/strategies/${ID}`,
      );
      await screen.findByRole("heading", { level: 1, name: "ETH Breakout" });
      const toggle = () => screen.getByRole("button", { name: "Connect a TradingView alert" });
      fireEvent.click(toggle());
      await press(copyUrl());
      await press(copyMessage());
      expect(copiedCount()).toBe(1);

      fireEvent.click(toggle());

      expect(screen.queryByText("Copied")).toBeNull();
      expect(screen.queryByRole("button", { name: "Copy URL" })).toBeNull();

      fireEvent.click(toggle());

      expect(screen.queryByText("Copied")).toBeNull();
      expect(statusBeside(copyUrl())).toBeEmptyDOMElement();
      expect(statusBeside(copyMessage())).toBeEmptyDOMElement();
    });

    it("test_the_url_copied_with_the_placeholder_then_show_secret_copied_is_gone", async () => {
      const writeText = stubClipboard();
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      await press(copyUrl());
      expect(statusBeside(copyUrl())).toHaveTextContent("Copied");

      fireEvent.click(showButton());
      await revealed();

      expect(statusBeside(copyUrl())).toBeEmptyDOMElement();
      expect(copiedCount()).toBe(0);
      // The clipboard still holds the placeholder URL, which is why "Copied" must not stand beside the real one.
      expect(writeText).toHaveBeenLastCalledWith(`${HOST}${PLACEHOLDER_URL}`);
    });

    it("test_the_url_copied_revealed_then_hide_secret_copied_is_gone", async () => {
      const writeText = stubClipboard();
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      fireEvent.click(showButton());
      await revealed();
      await press(copyUrl());
      expect(statusBeside(copyUrl())).toHaveTextContent("Copied");

      fireEvent.click(hideButton());

      expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`);
      expect(statusBeside(copyUrl())).toBeEmptyDOMElement();
      expect(writeText).toHaveBeenLastCalledWith(`${HOST}${URL_BASE}${SECRET}`);
    });

    it("test_after_that_showing_or_hiding_the_secret_again_does_not_bring_copied_back", async () => {
      stubClipboard();
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      await press(copyUrl());
      fireEvent.click(showButton());
      await revealed();
      expect(copiedCount()).toBe(0);

      // The URL on screen is the placeholder again, the very text that was copied; "Copied" still stays away.
      fireEvent.click(hideButton());
      expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`);
      expect(copiedCount()).toBe(0);

      fireEvent.click(showButton());
      await revealed();
      expect(copiedCount()).toBe(0);
    });

    // The render check alone already hides "Copied" while the URL differs, so each handler's clearing is
    // proved by the one case the other cannot cover: the Show that fails, and the Hide followed by a Show.
    it("test_a_show_that_fails_still_removes_copied_beside_the_placeholder_url", async () => {
      stubClipboard();
      setupHost(originAnswers(HOST), () => Promise.resolve(jsonResponse({ detail: "not configured" }, 503)));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      await press(copyUrl());
      expect(statusBeside(copyUrl())).toHaveTextContent("Copied");

      fireEvent.click(showButton());
      await screen.findByRole("alert");

      expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`);
      expect(statusBeside(copyUrl())).toBeEmptyDOMElement();
    });

    it("test_hiding_the_secret_and_showing_it_again_does_not_bring_back_a_copy_of_the_revealed_url", async () => {
      stubClipboard();
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      fireEvent.click(showButton());
      await revealed();
      await press(copyUrl());
      expect(statusBeside(copyUrl())).toHaveTextContent("Copied");

      fireEvent.click(hideButton());
      fireEvent.click(showButton());
      await revealed();

      expect(urlText()).toBe(`${HOST}${URL_BASE}${SECRET}`);
      expect(copiedCount()).toBe(0);
    });

    it("test_the_url_copied_as_the_path_alone_then_the_host_loads_copied_is_gone", async () => {
      const writeText = stubClipboard();
      const host = lateOrigin();
      setupHost(host.route);
      expect(urlText()).toBe(PLACEHOLDER_URL);
      await press(copyUrl());
      expect(statusBeside(copyUrl())).toHaveTextContent("Copied");
      expect(writeText).toHaveBeenLastCalledWith(PLACEHOLDER_URL);

      await host.arrive(HOST);

      expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`);
      expect(statusBeside(copyUrl())).toBeEmptyDOMElement();
      expect(copiedCount()).toBe(0);
    });

    it("test_the_messages_copied_survives_showing_and_hiding_the_secret", async () => {
      stubClipboard();
      setupHost(originAnswers(HOST));
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      await press(copyMessage());

      fireEvent.click(showButton());
      await revealed();
      expect(statusBeside(copyMessage())).toHaveTextContent("Copied");

      fireEvent.click(hideButton());
      expect(statusBeside(copyMessage())).toHaveTextContent("Copied");
      expect(copiedCount()).toBe(1);
    });

    it("test_the_clipboard_never_holds_something_the_screen_does_not_show_next_to_copied", async () => {
      const writeText = stubClipboard();
      const host = lateOrigin();
      setupHost(host.route);
      /** Whenever "Copied" stands beside a button, the last write for it is the text that button's source shows now. */
      const lastWrite = (isUrl: boolean) =>
        writeText.mock.calls
          .map(([text]) => String(text))
          .filter((text) => text.includes(URL_BASE) === isUrl)
          .at(-1);
      const check = () => {
        if (copiedBeside(copyUrl())) expect(lastWrite(true)).toBe(urlText());
        if (copiedBeside(copyMessage())) expect(lastWrite(false)).toBe(messageText());
      };

      await press(copyUrl());
      check();
      await press(copyMessage());
      check();
      await host.arrive(HOST);
      check();
      await press(copyUrl());
      check();
      expect(copiedBeside(copyUrl())).toBe(true);
      fireEvent.click(showButton());
      await revealed();
      check();
      expect(copiedBeside(copyUrl())).toBe(false);
      await press(copyUrl());
      check();
      expect(copiedBeside(copyUrl())).toBe(true);
      fireEvent.click(hideButton());
      check();
      expect(copiedBeside(copyUrl())).toBe(false);
      fireEvent.click(showButton());
      await revealed();
      check();
      fireEvent.click(hideButton());
      check();
      await press(copyUrl());
      check();
      expect(copiedBeside(copyUrl())).toBe(true);
      expect(copiedBeside(copyMessage())).toBe(false);
    });
  });

  it("renders its texts in Spanish", async () => {
    await i18n.changeLanguage("es");
    setup();

    expect(screen.getByRole("button", { name: "Mostrar el secreto" })).toBeInTheDocument();
    expect(screen.getByText(`${URL_BASE}<su WEBHOOK_SECRET>`)).toBeInTheDocument();
  });
});
