import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import { saveCredential } from "@/shared/api/credentials";
import { page } from "@/shared/auth/reauthenticate";
import i18n from "@/shared/i18n";
import {
  type ExtraRoute,
  jsonResponse,
  lock,
  pool,
  resetExchangeScope,
  storedKey,
  stubApi,
  unlock,
} from "@/test/harness";

/**
 * The typed secret (design § H). Two obviously fake sentinels stand for what the owner types: `K`
 * in "API key" and `S` in "API secret". No real credential is ever needed (`DRY_RUN` rule 1). Each
 * test looks for them everywhere they could leak, not only at what the code does, and runs once per
 * ending of a save: one that worked, each refusal, a network failure and a 401.
 */
const K = "FAKE-KEY-sentinel-not-a-credential-0001";
const S = "FAKE-SECRET-sentinel-not-a-credential-0002";
/** What the server says the last four characters are: they differ from the end of `K`. */
const ANSWER_LAST4 = "Z9y8";
const HERE = dirname(fileURLToPath(import.meta.url));
const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const CONSOLE_METHODS = ["log", "info", "warn", "error", "debug", "trace"] as const;

/** A server that echoes what it was sent, as the design says it must be able to without the panel showing it. */
const ECHO = `echoed ${K} and ${S}`;

interface Ending {
  name: string;
  /** What the server answers to the `PUT`. */
  respond: () => Promise<Response>;
}

function answer(status: number, body: Record<string, unknown>): () => Promise<Response> {
  return () => Promise.resolve(jsonResponse(body, status));
}

function refusal(status: number, outcome: string): Ending["respond"] {
  return answer(status, { outcome, detail: ECHO, missing: [] });
}

function validation(field: string | null): Ending["respond"] {
  const loc = field === null ? ["body"] : ["body", field];
  return answer(422, { detail: [{ type: "string_too_short", loc, msg: ECHO, input: `${K}${S}` }] });
}

const SAVED: Ending = {
  name: "a save that worked",
  respond: answer(200, {
    exchange: "bybit",
    last4: ANSWER_LAST4,
    warnings: [],
    facts: { trade_capable: true },
    detail: ECHO,
  }),
};

const ENDINGS: Ending[] = [
  SAVED,
  { name: "KEY_REJECTED", respond: refusal(422, "KEY_REJECTED") },
  { name: "WITHDRAW_PERMISSION", respond: refusal(422, "WITHDRAW_PERMISSION") },
  { name: "PERMISSIONS_UNAVAILABLE", respond: refusal(422, "PERMISSIONS_UNAVAILABLE") },
  { name: "VENUE_UNREACHABLE", respond: refusal(502, "VENUE_UNREACHABLE") },
  { name: "CONCURRENT_SAVE", respond: refusal(409, "CONCURRENT_SAVE") },
  { name: "EXCHANGE_HOLDS_REAL_EXPOSURE", respond: refusal(409, "EXCHANGE_HOLDS_REAL_EXPOSURE") },
  { name: "CONFIRMATION_REQUIRED", respond: refusal(422, "CONFIRMATION_REQUIRED") },
  { name: "CONFIRMATION_NOT_APPLICABLE", respond: refusal(422, "CONFIRMATION_NOT_APPLICABLE") },
  { name: "a 404", respond: answer(404, { detail: ECHO }) },
  { name: "a 503", respond: answer(503, { detail: ECHO }) },
  { name: "a validation error on api_key", respond: validation("api_key") },
  { name: "a validation error on api_secret", respond: validation("api_secret") },
  { name: "a validation error on neither", respond: validation(null) },
  { name: "a network failure", respond: () => Promise.reject(new TypeError(`offline ${ECHO}`)) },
  { name: "a 500", respond: answer(500, { detail: ECHO }) },
  { name: "a 401", respond: answer(401, { detail: ECHO }) },
];

const consoleSpies = CONSOLE_METHODS.map((method) => vi.spyOn(console, method).mockImplementation(() => undefined));

beforeEach(() => {
  unlock();
  resetExchangeScope();
  window.sessionStorage.clear();
  for (const spy of consoleSpies) spy.mockClear();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  lock();
  window.sessionStorage.clear();
  await i18n.changeLanguage("en");
});

interface Setup {
  fetchMock: ReturnType<typeof stubApi>;
  queryClient: QueryClient;
}

/** The whole app on Settings, with the `PUT` answered by the test and a Bybit key stored. */
function setup(respond: () => Promise<Response>, lists: { credentials?: () => unknown[] } = {}): Setup {
  const extra: ExtraRoute = (url, init) => {
    if (url.endsWith("/credentials/bybit") && init?.method === "PUT") return respond();
    if (url.endsWith("/credentials") && (init?.method ?? "GET") === "GET" && lists.credentials !== undefined) {
      return Promise.resolve(jsonResponse(lists.credentials()));
    }
    return undefined;
  };
  // Binance's pool is on, so its card is there with no key (decision 80): a second form to open.
  const fetchMock = stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit"), pool("binance")] }, {}, extra);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/settings"]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { fetchMock, queryClient };
}

function puts(fetchMock: ReturnType<typeof stubApi>) {
  return fetchMock.mock.calls.filter(([url, init]) => String(url).includes("/credentials/") && init?.method === "PUT");
}

function reads(fetchMock: ReturnType<typeof stubApi>) {
  return fetchMock.mock.calls.filter(
    ([url, init]) => /\/(credentials|pools)$/.test(String(url)) && (init?.method ?? "GET") === "GET",
  );
}

async function card(name: string): Promise<HTMLElement> {
  return screen.findByRole("article", { name });
}

/** A card's toggle, "Add key" or "Replace key" with the exchange after it. */
async function toggleOf(name: string): Promise<HTMLElement> {
  return within(await card(name)).findByRole("button", { name: /^(Add|Replace) key/ });
}

async function openBybit(): Promise<void> {
  fireEvent.click(await toggleOf("Bybit"));
  await screen.findByLabelText("API key");
}

const keyField = () => screen.getByLabelText("API key") as HTMLInputElement;
const secretField = () => screen.getByLabelText("API secret") as HTMLInputElement;
const submitButton = () => screen.getByRole("button", { name: "Check and save" });

function type(): { key: HTMLInputElement; secret: HTMLInputElement } {
  const key = keyField();
  const secret = secretField();
  fireEvent.change(key, { target: { value: K } });
  fireEvent.change(secret, { target: { value: S } });
  return { key, secret };
}

/** Opens Bybit's form, types both sentinels and presses the button; resolves when the attempt has ended. */
async function attempt(fetchMock: ReturnType<typeof stubApi>) {
  await openBybit();
  const fields = type();
  fireEvent.click(submitButton());
  await settled(fetchMock);
  return fields;
}

async function settled(fetchMock: ReturnType<typeof stubApi>): Promise<void> {
  await waitFor(() => expect(puts(fetchMock)).toHaveLength(1));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Checking…" })).not.toBeInTheDocument());
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

/** Everything a query holds that could leak: its key, its data and its error, with an error's own fields. */
function walk(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) =>
    item instanceof Error ? { ...item, name: item.name, message: item.message } : item,
  );
}

function leaks(text: string): string[] {
  return [K, S].filter((sentinel) => text.includes(sentinel));
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name) ? [path] : [];
  });
}

describe("row 1: the query cache", () => {
  it.each(ENDINGS)("test_no_query_cache_entry_holds_the_key_or_the_secret: $name", async ({ respond }) => {
    const { fetchMock, queryClient } = setup(respond);
    await attempt(fetchMock);

    const entries = queryClient.getQueryCache().getAll();
    expect(entries.length).toBeGreaterThan(0);
    for (const query of entries) {
      expect(leaks(walk({ key: query.queryKey, data: query.state.data, error: query.state.error }))).toEqual([]);
    }
  });
});

describe("row 2: the mutation cache", () => {
  it.each(ENDINGS)("test_no_mutation_cache_entry_exists_for_a_save: $name", async ({ respond }) => {
    const { fetchMock, queryClient } = setup(respond);
    await attempt(fetchMock);

    expect(queryClient.getMutationCache().getAll()).toEqual([]);
  });

  it("never passes the save to useMutation, in the form or in the client", () => {
    for (const file of [join(HERE, "KeyEntryForm.tsx"), join(HERE, "..", "..", "shared", "api", "credentials.ts")]) {
      const source = readFileSync(file, "utf8");
      expect(source.length, file).toBeGreaterThan(100);
      const code = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
      // credentials.ts may use `useQuery` for the list and `useMutation` for the delete (it carries no secret,
      // task 13.6.3), never `useMutation` for the save.
      const hook = /export function useDeleteCredential[\s\S]*?\r?\n\}\r?\n/.exec(code)?.[0] ?? "";
      const withoutHookAndImport = code.replace(hook, "").replace(/^import .*$/gm, "");
      expect(withoutHookAndImport, file).not.toMatch(/useMutation/);
      expect(hook, file).not.toMatch(/saveCredential|api_key|api_secret|apiKey|apiSecret/);
    }
  });
});

describe("row 3: no state holds the typed text", () => {
  it("has no value= and no defaultValue= on either field of KeyEntryForm.tsx", () => {
    const source = readFileSync(join(HERE, "KeyEntryForm.tsx"), "utf8");
    expect(source.length).toBeGreaterThan(100);
    expect(source).not.toMatch(/\bvalue=/);
    expect(source).not.toMatch(/\bdefaultValue=/);
  });
});

describe("row 4: no attribute of the document", () => {
  it("test_no_attribute_of_the_document_holds_the_key_or_the_secret: after typing", async () => {
    setup(SAVED.respond);
    await openBybit();
    const { key, secret } = type();

    expect(key.value).toBe(K);
    expect(secret.value).toBe(S);
    expect(leaks(document.body.innerHTML)).toEqual([]);
    expect(key.hasAttribute("value")).toBe(false);
    expect(secret.hasAttribute("value")).toBe(false);
  });

  it.each(ENDINGS)("test_no_attribute_of_the_document_holds_the_key_or_the_secret: after $name", async ({ respond }) => {
    const { fetchMock } = setup(respond);
    await attempt(fetchMock);

    expect(leaks(document.body.innerHTML)).toEqual([]);
    // Where a form is still open (a refusal keeps it): neither of its fields carries a `value` attribute.
    // After a 401 the token gate is on screen instead, and its own field is not the subject here.
    for (const label of ["API key", "API secret"]) {
      const field = screen.queryByLabelText(label);
      if (field !== null) expect(field.hasAttribute("value"), label).toBe(false);
    }
  });
});

describe("row 5: no text on screen", () => {
  it.each(ENDINGS)(
    "test_no_text_on_screen_holds_what_was_typed_even_when_the_server_echoes_it: $name",
    async ({ respond }) => {
      const { fetchMock } = setup(respond);
      await attempt(fetchMock);

      // The text of the document; what a field holds is not text, and row 4 looks at the markup.
      expect(leaks(document.body.textContent ?? "")).toEqual([]);
    },
  );
});

describe("row 6: the console", () => {
  it.each(ENDINGS)("test_nothing_is_written_to_the_console: $name", async ({ respond }) => {
    const { fetchMock } = setup(respond);
    await attempt(fetchMock);

    for (const spy of consoleSpies) expect(spy.mock.calls).toEqual([]);
  });

  it("writes nothing to the console from the settings feature or the credentials client (source)", () => {
    const files = [...sourceFiles(HERE), join(HERE, "..", "..", "shared", "api", "credentials.ts")];
    expect(files.length).toBeGreaterThan(3);
    for (const file of files) expect(readFileSync(file, "utf8"), file).not.toMatch(/console\./);
  });

  it("resolves, never rejects, for a fetch that throws a plain Error holding the sentinels", async () => {
    vi.stubGlobal("fetch", () => {
      throw new Error(`boom ${ECHO}`);
    });

    const result = await saveCredential("bybit", K, S, []);

    expect(result).toEqual({ kind: "refused", reason: "noAnswer", missing: [], status: 0 });
    expect(leaks(JSON.stringify(result))).toEqual([]);
  });
});

describe("row 8: the URL and the request", () => {
  it.each(ENDINGS)(
    "test_the_request_is_one_put_to_the_exchange_path_with_the_key_only_in_its_body: $name",
    async ({ respond }) => {
      const { fetchMock } = setup(respond);
      await attempt(fetchMock);

      const sent = puts(fetchMock);
      expect(sent).toHaveLength(1);
      const [url, init] = sent[0] as [string, RequestInit];
      expect(String(url)).toMatch(/\/credentials\/bybit$/);
      expect(JSON.parse(String(init.body))).toEqual({ api_key: K, api_secret: S });
      // Every argument of every request other than that one body holds neither.
      for (const [otherUrl, otherInit] of fetchMock.mock.calls) {
        const { body: _body, ...rest } = (otherInit ?? {}) as RequestInit;
        expect(leaks(JSON.stringify([String(otherUrl), rest, [...new Headers(rest.headers).entries()]]))).toEqual([]);
        if (otherInit?.method !== "PUT") expect(leaks(String(otherInit?.body ?? ""))).toEqual([]);
      }
    },
  );

  it("test_neither_field_has_a_name", async () => {
    setup(SAVED.respond);
    await openBybit();

    expect(keyField().hasAttribute("name")).toBe(false);
    expect(secretField().hasAttribute("name")).toBe(false);
  });
});

describe("row 9: closing the form", () => {
  it("test_closing_the_form_and_opening_it_again_shows_two_empty_fields", async () => {
    setup(SAVED.respond);
    await openBybit();
    type();

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByLabelText("API key")).not.toBeInTheDocument());
    fireEvent.click(await toggleOf("Bybit"));

    expect((await screen.findByLabelText("API key") as HTMLInputElement).value).toBe("");
    expect(secretField().value).toBe("");
    expect(leaks(document.body.innerHTML)).toEqual([]);
  });
});

describe("row 10: leaving, switching exchange and a 401", () => {
  it("test_leaving_settings_and_coming_back_shows_no_open_form", async () => {
    setup(SAVED.respond);
    await openBybit();
    type();

    fireEvent.click(screen.getAllByRole("link", { name: "Overview" })[0] as HTMLElement);
    await screen.findByRole("heading", { level: 1, name: "Overview" });
    expect(screen.queryByLabelText("API key")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("link", { name: "Settings" })[0] as HTMLElement);
    await screen.findByRole("heading", { level: 1, name: "Settings" });
    await card("Bybit");

    expect(screen.queryByLabelText("API key")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 4 })).not.toBeInTheDocument();
    expect(leaks(document.body.innerHTML)).toEqual([]);
  });

  it("test_opening_another_exchange_closes_and_empties_this_one", async () => {
    setup(SAVED.respond);
    await openBybit();
    type();

    fireEvent.click(await toggleOf("Binance"));

    await waitFor(() => expect(screen.getAllByLabelText("API key")).toHaveLength(1));
    expect(within(await card("Binance")).getByLabelText("API key")).toBeInTheDocument();
    expect(within(await card("Bybit")).queryByLabelText("API key")).not.toBeInTheDocument();
    expect(keyField().value).toBe("");
    expect(leaks(document.body.innerHTML)).toEqual([]);

    fireEvent.click(await toggleOf("Bybit"));
    await waitFor(() => expect(within(screen.getByRole("article", { name: "Bybit" })).queryByLabelText("API key")).toBeInTheDocument());
    expect(keyField().value).toBe("");
    expect(secretField().value).toBe("");
  });

  it("test_a_401_during_a_save_reloads_the_page_and_leaves_nothing_typed", async () => {
    const { fetchMock } = setup(answer(401, { detail: ECHO }));
    const reload = vi.spyOn(page, "reload").mockImplementation(() => undefined);
    await openBybit();
    type();
    const readsBefore = reads(fetchMock).length;

    fireEvent.click(submitButton());
    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    await settled(fetchMock);

    expect(keyField().value).toBe("");
    expect(secretField().value).toBe("");
    expect(leaks(document.body.innerHTML)).toEqual([]);
    expect(leaks(document.body.textContent ?? "")).toEqual([]);
    // Nothing is recorded, re-read or focused: the page is being loaded again, through Access's sign-in.
    expect(reads(fetchMock)).toHaveLength(readsBefore);
    expect(document.activeElement?.tagName === "INPUT" && document.activeElement.getAttribute("type") === "password").toBe(false);
  });
});

describe("row 11: the network, twice", () => {
  it("test_a_second_click_and_an_enter_while_checking_send_nothing", async () => {
    let release: (response: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const { fetchMock } = setup(() => pending);
    await openBybit();
    type();

    fireEvent.click(submitButton());
    await waitFor(() => expect(puts(fetchMock)).toHaveLength(1));
    const form = document.querySelector("form");
    expect(form).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Checking…" }));
    fireEvent.submit(form as HTMLFormElement);
    fireEvent.keyDown(keyField(), { key: "Enter" });

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(puts(fetchMock)).toHaveLength(1);
    await act(async () => {
      release(jsonResponse({ exchange: "bybit", last4: ANSWER_LAST4, warnings: [], facts: { trade_capable: true } }));
    });
  });

  it("test_a_failed_save_is_not_retried", async () => {
    const { fetchMock } = setup(answer(500, { detail: ECHO }));
    await attempt(fetchMock);

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 60));
    });
    expect(puts(fetchMock)).toHaveLength(1);
  });
});

describe("row 12: both fields are emptied", () => {
  it.each(ENDINGS)("test_both_fields_are_empty_after_every_ending: $name", async ({ name, respond }) => {
    const { fetchMock } = setup(respond);
    const { key, secret } = await attempt(fetchMock);

    if (name === SAVED.name) {
      // A save that worked closes the form (decision 57): neither field is in the document.
      expect(key.isConnected).toBe(false);
      expect(secret.isConnected).toBe(false);
      expect(screen.queryByLabelText("API key")).not.toBeInTheDocument();
      fireEvent.click(await toggleOf("Bybit"));
      expect((await screen.findByLabelText("API key") as HTMLInputElement).value).toBe("");
      expect(secretField().value).toBe("");
    } else {
      // Asserted on BOTH, also for a 401 where the form has left the document with the page.
      expect(key.value).toBe("");
      expect(secret.value).toBe("");
    }
  });
});

describe("row 13: what the browser is asked to keep", () => {
  it("test_the_fields_carry_the_attributes_that_ask_the_browser_to_keep_nothing", async () => {
    setup(SAVED.respond);
    await openBybit();
    const key = keyField();
    const secret = secretField();

    expect(key).toHaveAttribute("type", "text");
    expect(key).toHaveAttribute("autocomplete", "off");
    expect(key).toHaveAttribute("spellcheck", "false");
    expect(key).toHaveAttribute("autocapitalize", "off");
    expect(key).toHaveAttribute("autocorrect", "off");
    expect(key.hasAttribute("name")).toBe(false);
    expect(secret).toHaveAttribute("type", "password");
    expect(secret).toHaveAttribute("autocomplete", "new-password");
    expect(secret.hasAttribute("name")).toBe(false);
  });
});

describe("row 15: storage", () => {
  it.each(ENDINGS)("test_no_storage_holds_what_was_typed: $name", async ({ respond }) => {
    const { fetchMock } = setup(respond);
    await attempt(fetchMock);

    const stored = JSON.stringify([
      Object.entries(window.localStorage),
      Object.entries(window.sessionStorage),
    ]);
    expect(leaks(stored)).toEqual([]);
  });
});

describe("row 16: the last four come from the answer", () => {
  it("test_the_saved_status_reads_the_last4_of_the_answer_not_of_the_field", async () => {
    let stored = storedKey("bybit", { last4: "1234" });
    const { fetchMock } = setup(SAVED.respond, { credentials: () => [stored] });
    stored = storedKey("bybit", { last4: ANSWER_LAST4 });
    await attempt(fetchMock);

    const region = await waitFor(() => {
      const found = screen.getAllByRole("status").find((node) => node.textContent === `Key ending in ${ANSWER_LAST4} saved.`);
      expect(found).toBeDefined();
      return found as HTMLElement;
    });
    expect(region).toBeInTheDocument();
    expect(document.body.textContent).toContain(ANSWER_LAST4);
    // The end of what was typed is not what is said.
    expect(document.body.textContent).not.toContain(K.slice(-4));
    expect(leaks(document.body.innerHTML)).toEqual([]);
  });

  it("test_an_answer_whose_last4_is_not_four_characters_is_said_as_key_saved", async () => {
    const whole = answer(200, { exchange: "bybit", last4: K, warnings: [], facts: { trade_capable: true } });
    const { fetchMock } = setup(whole);
    await attempt(fetchMock);

    await waitFor(() => {
      expect(screen.getAllByRole("status").some((node) => node.textContent === "Key saved.")).toBe(true);
    });
    expect(leaks(document.body.innerHTML)).toEqual([]);
    expect(leaks(document.body.textContent ?? "")).toEqual([]);
  });
});

describe("row 17: Close while checking", () => {
  it("test_close_is_disabled_while_checking", async () => {
    const pending = new Promise<Response>(() => undefined);
    const { fetchMock } = setup(() => pending);
    await openBybit();
    type();

    fireEvent.click(submitButton());
    await waitFor(() => expect(puts(fetchMock)).toHaveLength(1));

    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Checking…" })).toBeDisabled();
  });
});
