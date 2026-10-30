import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { webhookMessage } from "@/features/strategies/webhook-message";
import { WebhookMessage } from "@/features/strategies/WebhookMessage";
import i18n from "@/shared/i18n";
import { jsonResponse, lock, resetExchangeScope, unlock } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const OTHER_ID = "22222222-2222-4222-8222-222222222222";
const SECRET = "s3cr3t-Vh4lu3-Zq9";
/** A secret that needs percent-encoding, and that is easy to search for if it leaks. */
const AWKWARD = "p&q/r s";
const AWKWARD_ENCODED = "p%26q%2Fr%20s";
const URL_BASE = "/webhook/tradingview?secret=";
const PLACEHOLDER_URL = `${URL_BASE}<your secret>`;
const ORIGIN_PATH = "/api/webhook-origin";
const REGENERATE_PATH = `/api/strategies/${ID}/webhook-secret`;
const HOST = "https://hook.example.com";
const HOST_UNSET =
  "No public host is configured for the webhook, so only the path is shown. Put your webhook's host in front of it.";
const HOST_ERROR = "The webhook's host could not be loaded, so only the path is shown.";
const COPY_FAILED = "Could not copy. Select the text and copy it by hand.";
const WARNING =
  "This URL contains the strategy's secret. It is shown only once: copy it now. It will not be shown again, and if you lose it you will have to regenerate the secret.";
const CONSOLE_METHODS = ["log", "info", "warn", "error", "debug"] as const;

type Answer = () => Promise<Response>;
const originAnswers =
  (origin: unknown): Answer =>
  () =>
    Promise.resolve(jsonResponse({ origin }));
const regenerates =
  (secret: unknown): Answer =>
  () =>
    Promise.resolve(jsonResponse({ webhook_secret: secret }));

interface Call {
  url: string;
  init: RequestInit | undefined;
}

interface Options {
  origin?: Answer;
  regenerate?: Answer;
  archived?: boolean;
}

/** The block, with the webhook's host answered by `origin` and the regenerate route by `regenerate`. */
function setup(options: Options = {}) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      if (url.endsWith(ORIGIN_PATH)) return (options.origin ?? originAnswers(HOST))();
      if (url.endsWith("/webhook-secret")) return (options.regenerate ?? regenerates(SECRET))();
      return Promise.reject(new Error(`unexpected fetch: ${url}`));
    }),
  );
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = (strategyId: string) => (
    <QueryClientProvider client={queryClient}>
      <WebhookMessage strategyId={strategyId} archived={options.archived ?? false} />
    </QueryClientProvider>
  );
  const view = render(tree(ID));
  const regenerateCalls = () => calls.filter((call) => call.url.endsWith("/webhook-secret"));
  return { calls, queryClient, regenerateCalls, tree, ...view };
}

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

// A Copy button is found by its place and not by its name: its name becomes "Copied" once it is used.
const copyMessage = () =>
  within(
    screen.getByRole("group", { name: i18n.t("strategies.webhook.messageLabel") }).parentElement as HTMLElement,
  ).getByRole("button");
/** The Copy button of the issued URL: the last button in the URL's row. */
const copyIssued = () => {
  const row = (document.querySelector("code") as HTMLElement).parentElement as HTMLElement;
  const buttons = within(row).getAllByRole("button");
  return buttons[buttons.length - 1] as HTMLElement;
};
const statusBeside = (button: HTMLElement) => within(button.parentElement as HTMLElement).getByRole("status");
const press = (button: HTMLElement) =>
  act(async () => {
    fireEvent.click(button);
  });
const messageText = () => screen.getByRole("group", { name: "Alert message" }).textContent;
const regenerateButton = () => screen.getByRole("button", { name: "Regenerate secret" });
const confirmDialog = () => screen.getByRole("dialog", { name: "Regenerate the secret?" });
const confirmButton = () => within(confirmDialog()).getByRole("button", { name: "Regenerate" });

/** Opens the confirmation and confirms it: the new URL is then on screen. */
async function regenerateNow() {
  fireEvent.click(regenerateButton());
  fireEvent.click(confirmButton());
  await screen.findByText(WARNING);
}

const consoleSpies = CONSOLE_METHODS.map((method) => vi.spyOn(console, method).mockImplementation(() => undefined));

/** Every place a leak could be read from, other than the clipboard. */
const leaksOf = (queryClient: QueryClient, secrets: readonly string[]): string[] => {
  const places = [
    document.body.innerHTML,
    JSON.stringify(
      queryClient
        .getQueryCache()
        .findAll()
        .map((query) => [query.queryKey, query.state.data]),
    ),
    JSON.stringify(
      queryClient
        .getMutationCache()
        .getAll()
        .map((mutation) => [mutation.state.data, mutation.state.variables]),
    ),
    JSON.stringify({ ...window.localStorage }),
    JSON.stringify({ ...window.sessionStorage }),
    ...consoleSpies.map((spy) => JSON.stringify(spy.mock.calls)),
  ];
  return places.filter((place) => secrets.some((secret) => place.includes(secret)));
};

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
  await i18n.changeLanguage("en");
});

describe("WebhookMessage", () => {
  it("shows the URL with a placeholder instead of the secret, and offers no way to read the secret", async () => {
    const { calls, regenerateCalls } = setup();

    await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
    await settle();

    expect(screen.queryByRole("button", { name: "Show secret" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Copy URL" })).toBeNull();
    expect(regenerateCalls()).toHaveLength(0);
    expect(calls.every((call) => call.url.endsWith(ORIGIN_PATH))).toBe(true);
  });

  it("renders the copy-ready alert message for the strategy", () => {
    setup();

    expect(messageText()).toBe(webhookMessage(ID));
    expect(JSON.parse(messageText() ?? "")).toMatchObject({ signal_type: ID, symbol: "{{ticker}}" });
  });

  it("draws an aria-hidden Copy left of the text of Copy message, its name unchanged", () => {
    setup();

    const button = copyMessage();
    const svg = button.querySelector("svg");
    expect(svg).toHaveClass("lucide-copy", "size-4", "shrink-0");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(button.firstElementChild).toBe(svg);
    expect(button).toHaveAccessibleName("Copy message");
  });

  it("copies the message shown, and the button reads Copied", async () => {
    const writeText = stubClipboard();
    setup();

    await press(copyMessage());

    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith(webhookMessage(ID));
    expect(copyMessage()).toHaveAccessibleName("Copied");
    expect(statusBeside(copyMessage())).toHaveTextContent("Copied");
  });

  it.each([
    ["no clipboard", () => setClipboard(undefined)],
    ["a rejected write", () => setClipboard({ writeText: vi.fn().mockRejectedValue(new DOMException("denied")) })],
  ])("says it could not copy, in the loss colour, with %s", async (_name, arrange) => {
    arrange();
    setup();

    await press(copyMessage());

    expect(statusBeside(copyMessage())).toHaveTextContent(COPY_FAILED);
    expect(statusBeside(copyMessage())).toHaveClass("text-loss");
    expect(copyMessage()).toHaveAccessibleName("Copy message");
  });

  describe("the host of the URL", () => {
    it("puts a configured host in front of the path", async () => {
      setup();

      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      expect(screen.queryByText(HOST_UNSET)).toBeNull();
      expect(screen.queryByText(HOST_ERROR)).toBeNull();
    });

    it("shows the path alone while the host loads", async () => {
      setup({ origin: () => new Promise<Response>(() => undefined) });
      await settle();

      expect(urlText()).toBe(PLACEHOLDER_URL);
      expect(screen.queryByText(HOST_UNSET)).toBeNull();
      expect(screen.queryByText(HOST_ERROR)).toBeNull();
    });

    it("shows the path alone and says no public host is configured when the origin is null", async () => {
      setup({ origin: originAnswers(null) });

      await waitFor(() => expect(screen.queryByText(HOST_UNSET)).toBeInTheDocument());

      expect(urlText()).toBe(PLACEHOLDER_URL);
    });

    it.each([
      ["a 500", () => Promise.resolve(jsonResponse({ detail: "boom" }, 500))],
      ["a network failure", () => Promise.reject(new TypeError("offline"))],
      ["an origin with a path", originAnswers(`${HOST}/hook`)],
    ] as Array<[string, Answer]>)("shows the path alone and says the host could not be loaded after %s", async (_name, origin) => {
      setup({ origin });

      await waitFor(() => expect(screen.queryByText(HOST_ERROR)).toBeInTheDocument());

      expect(urlText()).toBe(PLACEHOLDER_URL);
    });

    it("draws the URL as text, never inside an anchor, and requests nothing at the origin", async () => {
      const { calls } = setup();
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      const code = screen.getByLabelText("Webhook URL");
      fireEvent.click(code);
      await settle();

      expect(code.tagName).toBe("CODE");
      expect(code.closest("a")).toBeNull();
      expect(document.querySelector("a, form, [href], [action]")).toBeNull();
      expect(calls.filter((call) => call.url.includes("hook.example.com"))).toEqual([]);
    });
  });

  describe("regenerating the secret", () => {
    it("asks first, says the old secret stops working, and sends nothing until it is confirmed", async () => {
      const { regenerateCalls } = setup();
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      fireEvent.click(regenerateButton());

      const dialog = confirmDialog();
      expect(dialog).toHaveTextContent(
        "The current secret stops working as soon as you confirm. Every alert that still uses it will be refused until you update its URL.",
      );
      expect(regenerateCalls()).toHaveLength(0);

      fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
      await settle();

      expect(screen.queryByRole("dialog")).toBeNull();
      expect(regenerateCalls()).toHaveLength(0);
      expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`);
    });

    it("confirming posts to the strategy's route, then shows the new URL with its secret and the warning", async () => {
      const { regenerateCalls } = setup({ regenerate: regenerates(AWKWARD) });
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      await regenerateNow();

      expect(regenerateCalls()).toHaveLength(1);
      const call = regenerateCalls()[0];
      expect(call?.url.endsWith(REGENERATE_PATH)).toBe(true);
      expect(call?.init?.method).toBe("POST");
      expect(call?.url).not.toContain(AWKWARD_ENCODED);
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(urlText()).toBe(`${HOST}${URL_BASE}${AWKWARD_ENCODED}`);
      expect(screen.queryByText(`${HOST}${PLACEHOLDER_URL}`)).toBeNull();
      expect(screen.getByText(WARNING)).toBeInTheDocument();
    });

    it("copies the new URL with its secret from the shared Copy button", async () => {
      const writeText = stubClipboard();
      setup({ regenerate: regenerates(AWKWARD) });
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      await regenerateNow();

      await press(copyIssued());

      expect(writeText).toHaveBeenCalledTimes(1);
      expect(writeText).toHaveBeenCalledWith(`${HOST}${URL_BASE}${AWKWARD_ENCODED}`);
      expect(copyIssued()).toHaveAccessibleName("Copied");
    });

    it("puts the placeholder back and leaves no secret anywhere when it is dismissed", async () => {
      const { queryClient } = setup();
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      await regenerateNow();
      expect(urlText()).toBe(`${HOST}${URL_BASE}${SECRET}`);

      fireEvent.click(screen.getByRole("button", { name: "Done" }));

      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      expect(screen.queryByText(WARNING)).toBeNull();
      await waitFor(() => expect(leaksOf(queryClient, [SECRET])).toEqual([]));
    });

    it("leaves no secret in the cache, storage or console when the view is left", async () => {
      const writeText = stubClipboard();
      const { queryClient, unmount } = setup();
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      await regenerateNow();
      await press(copyIssued());
      expect(JSON.stringify(writeText.mock.calls)).toContain(SECRET);
      // While it is on screen it is in the page and in the one mutation result, and nowhere else.
      expect(JSON.stringify({ ...window.localStorage, ...window.sessionStorage })).not.toContain(SECRET);
      expect(JSON.stringify(queryClient.getQueryCache().findAll().map((query) => query.queryKey))).not.toContain(SECRET);

      unmount();

      await waitFor(() => expect(queryClient.getMutationCache().getAll()).toHaveLength(0));
      expect(leaksOf(queryClient, [SECRET])).toEqual([]);
    });

    it("starts from the placeholder for another strategy", async () => {
      const { queryClient, tree, rerender } = setup();
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      await regenerateNow();

      rerender(tree(OTHER_ID));

      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      expect(screen.queryByText(WARNING)).toBeNull();
      await waitFor(() => expect(leaksOf(queryClient, [SECRET])).toEqual([]));
    });

    it("disables the confirm button while the request is in flight, and sends no second one", async () => {
      let answer: (response: Response) => void = () => undefined;
      const { regenerateCalls } = setup({ regenerate: () => new Promise<Response>((resolve) => (answer = resolve)) });
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      fireEvent.click(regenerateButton());

      fireEvent.click(confirmButton().closest("button") as HTMLElement);
      await settle();

      const pending = within(confirmDialog()).getByRole("button", { name: "Regenerating…" });
      expect(pending).toBeDisabled();
      fireEvent.click(pending);
      await settle();
      expect(regenerateCalls()).toHaveLength(1);

      await act(async () => {
        answer(jsonResponse({ webhook_secret: SECRET }));
        await new Promise((resolve) => setTimeout(resolve, 30));
      });

      expect(urlText()).toBe(`${HOST}${URL_BASE}${SECRET}`);
    });

    it.each([
      [
        "an archived strategy (409)",
        () => Promise.resolve(jsonResponse({ detail: { error: "STRATEGY_ARCHIVED", message: "archived" } }, 409)),
        "This strategy is archived and can no longer be changed.",
      ],
      [
        "a strategy that is gone (404)",
        () => Promise.resolve(jsonResponse({ detail: "Not Found" }, 404)),
        "This strategy no longer exists.",
      ],
      [
        "a server error",
        () => Promise.resolve(jsonResponse({ detail: "boom" }, 500)),
        "The secret was not regenerated. Try again.",
      ],
      ["a body without a secret", regenerates(undefined), "The secret was not regenerated. Try again."],
    ] as Array<[string, Answer, string]>)("keeps the confirmation open and says why after %s", async (_name, regenerate, text) => {
      setup({ regenerate });
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));
      fireEvent.click(regenerateButton());

      fireEvent.click(confirmButton());

      expect(await within(confirmDialog()).findByRole("alert")).toHaveTextContent(text);
      expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`);
      expect(screen.queryByText(WARNING)).toBeNull();
    });

    it("cannot be asked of an archived strategy", async () => {
      const { regenerateCalls } = setup({ archived: true });
      await waitFor(() => expect(urlText()).toBe(`${HOST}${PLACEHOLDER_URL}`));

      expect(regenerateButton()).toBeDisabled();
      fireEvent.click(regenerateButton());
      await settle();

      expect(screen.queryByRole("dialog")).toBeNull();
      expect(regenerateCalls()).toHaveLength(0);
    });
  });

  describe.each([
    {
      language: "en",
      urlLabel: "Webhook URL",
      regenerate: "Regenerate secret",
      title: "Regenerate the secret?",
      confirm: "Regenerate",
      warning: WARNING,
      done: "Done",
      copyUrl: "Copy URL",
      placeholder: `${URL_BASE}<your secret>`,
    },
    {
      language: "es",
      urlLabel: "URL del webhook",
      regenerate: "Regenerar el secreto",
      title: "¿Regenerar el secreto?",
      confirm: "Regenerar",
      warning:
        "Esta URL contiene el secreto de la estrategia. Se muestra una sola vez: cópiela ahora. No se volverá a mostrar y, si la pierde, deberá regenerar el secreto.",
      done: "Listo",
      copyUrl: "Copiar URL",
      placeholder: `${URL_BASE}<su secreto>`,
    },
  ])("the texts in $language", (T) => {
    beforeEach(async () => {
      await act(() => i18n.changeLanguage(T.language));
    });

    it("renders the placeholder, the regenerate flow, the warning and the shared buttons", async () => {
      setup();
      await waitFor(() => expect(screen.getByLabelText(T.urlLabel).textContent).toBe(`${HOST}${T.placeholder}`));

      fireEvent.click(screen.getByRole("button", { name: T.regenerate }));
      const dialog = screen.getByRole("dialog", { name: T.title });
      fireEvent.click(within(dialog).getByRole("button", { name: T.confirm }));

      expect(await screen.findByText(T.warning)).toBeInTheDocument();
      expect(copyIssued()).toHaveAccessibleName(T.copyUrl);
      expect(screen.getByRole("button", { name: T.done })).toBeInTheDocument();
      cleanup();
    });
  });
});
