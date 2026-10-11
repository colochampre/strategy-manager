import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KeyEntryForm, type KeyEntryFormProps } from "@/features/settings/KeyEntryForm";
import { useCredentials } from "@/shared/api/credentials";
import { usePools } from "@/shared/api/pools";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { type ExtraRoute, jsonResponse, lock, pool, resetExchangeScope, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const AMBER = /\b(?:bg|text|border|ring|outline|fill|stroke|divide)-decision\b/;

const HELP_VERIFIED =
  "Before saving, the key is tried with a real read at Bybit. A key that can withdraw funds is refused. A key that cannot trade is saved with a warning.";
const HELP_CONFIRMED =
  "Before saving, the key is tried with a real read at Binance. Binance does not let this panel check what the key may do, so you confirm it here.";
const REPLACE_NOTE = "Saving replaces the key stored now, also when the new key cannot trade.";
const CONFIRM_HELP =
  "If the key lacks Enable Futures, Binance rejects the first live order and you get a Telegram alert. Nothing checks the withdrawal setting: it rests on your word.";
const WITHDRAWALS = "I confirmed in Binance that this key has withdrawals disabled";
const FUTURES = "I confirmed in Binance that this key has Enable Futures";
const BINANCE_CONFIRMATIONS = ["withdrawals_disabled_confirmed", "futures_enabled_confirmed"] as const;

/** Two fake values the tests type; no real credential is ever needed. */
const KEY = "FAKE-KEY-sentinel-not-a-credential-0001";
const SECRET = "FAKE-SECRET-sentinel-not-a-credential-0002";
const ANSWER = { exchange: "bybit", last4: "Z9y8", warnings: [], facts: { trade_capable: true } };

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

interface Rendered {
  props: KeyEntryFormProps;
  queryClient: QueryClient;
  fetchMock: ReturnType<typeof stubApi>;
  /** Takes the form out of the document, as leaving the page does, keeping the query client. */
  rerenderWithoutForm: () => void;
}

/** The form alone, on its own query client, with the `PUT` of its exchange answered by `respond`. */
function renderForm(
  overrides: Partial<KeyEntryFormProps> = {},
  respond: () => Promise<Response> = () => Promise.resolve(jsonResponse(ANSWER)),
  withReads = false,
): Rendered {
  const props: KeyEntryFormProps = {
    id: "key-form-bybit",
    exchange: "bybit",
    name: "Bybit",
    hasKey: false,
    confirmations: [],
    onClose: vi.fn(),
    onSaved: vi.fn(),
    onBusyChange: vi.fn(),
    ...overrides,
  };
  const extra: ExtraRoute = (url, init) =>
    url.endsWith(`/credentials/${props.exchange}`) && init?.method === "PUT" ? respond() : undefined;
  const fetchMock = stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit")] }, {}, extra);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={queryClient}>
      {withReads && <Reads />}
      <KeyEntryForm {...props} />
    </QueryClientProvider>,
  );
  const rerenderWithoutForm = () =>
    view.rerender(<QueryClientProvider client={queryClient}>{withReads && <Reads />}</QueryClientProvider>);
  return { props, queryClient, fetchMock, rerenderWithoutForm };
}

/** The two lists the page holds, so that a re-read has queries to read again. */
function Reads() {
  useCredentials();
  usePools();
  return null;
}

/** The GETs of the two lists so far. */
function listReads(fetchMock: ReturnType<typeof stubApi>) {
  return fetchMock.mock.calls.filter(
    ([url, init]) => /\/(credentials|pools)$/.test(String(url)) && (init?.method ?? "GET") === "GET",
  );
}

function puts(fetchMock: ReturnType<typeof stubApi>) {
  return fetchMock.mock.calls.filter(([url, init]) => String(url).includes("/credentials/") && init?.method === "PUT");
}

/** An element that must be there: a missing one fails here as an assertion, not as a query error. */
function found<T extends HTMLElement>(element: T | null, label: string): T {
  expect(element, label).toBeInTheDocument();
  return element as T;
}

const keyField = () => found(screen.queryByLabelText<HTMLInputElement>("API key"), "API key");
const secretField = () => found(screen.queryByLabelText<HTMLInputElement>("API secret"), "API secret");
const submit = () => found(screen.queryByRole<HTMLButtonElement>("button", { name: "Check and save" }), "Check and save");
const formElement = () => found(document.querySelector<HTMLFormElement>("form"), "the form");

function typeBoth(key = KEY, secret = SECRET) {
  fireEvent.change(keyField(), { target: { value: key } });
  fireEvent.change(secretField(), { target: { value: secret } });
}

function tick(label: string) {
  fireEvent.click(found(screen.queryByLabelText<HTMLInputElement>(label), label));
}

describe("the form's shape (design § F)", () => {
  it.each([
    [false, "Add a Bybit key"],
    [true, "Replace the Bybit key"],
  ])("is a section named by its h4 title, hasKey %s: %s", (hasKey, title) => {
    renderForm({ hasKey });

    const heading = found(screen.queryByRole("heading", { level: 4, name: title }), title);
    expect(heading.tagName).toBe("H4");
    const section = found(screen.queryByRole("region", { name: title }), "the section");
    expect(section.tagName).toBe("SECTION");
    expect(section).toContainElement(heading);
    expect(section).toHaveAttribute("id", "key-form-bybit");
    expect(section).toHaveClass("border", "border-dashed", "border-rule-strong");
  });

  it("has two fields, each with a label, each 44 px tall on the ground colour, both described by the help", () => {
    renderForm();

    for (const field of [keyField(), secretField()]) {
      expect(field).toHaveClass("min-h-11", "bg-ground", "border-rule");
      expect(field).toHaveAccessibleDescription(HELP_VERIFIED);
    }
    expect(keyField().tagName).toBe("INPUT");
    expect(secretField().tagName).toBe("INPUT");
  });

  it("says the help of an exchange with no confirmations, in ink-3", () => {
    renderForm();

    expect(found(screen.queryByText(HELP_VERIFIED), "help")).toHaveClass("text-ink-3");
    expect(screen.queryByText(HELP_CONFIRMED)).not.toBeInTheDocument();
  });

  it("says the other help for an exchange with confirmations", () => {
    renderForm({ exchange: "binance", name: "Binance", confirmations: BINANCE_CONFIRMATIONS });

    expect(found(screen.queryByText(HELP_CONFIRMED), "help")).toHaveClass("text-ink-3");
    expect(screen.queryByText(HELP_VERIFIED)).not.toBeInTheDocument();
  });

  it("warns about replacing only when a key is stored", () => {
    renderForm({ hasKey: true });
    expect(found(screen.queryByText(REPLACE_NOTE), "the replace note")).toHaveClass("text-ink-3");
  });

  it("does not warn about replacing when no key is stored", () => {
    renderForm({ hasKey: false });
    expect(screen.queryByText(HELP_VERIFIED)).toBeInTheDocument();
    expect(screen.queryByText(REPLACE_NOTE)).not.toBeInTheDocument();
  });

  it("test_bybit_form_shows_no_confirmation_checkboxes_and_sends_none", async () => {
    const { fetchMock } = renderForm();
    expect(screen.queryAllByRole("checkbox")).toEqual([]);
    expect(screen.queryByRole("group")).not.toBeInTheDocument();

    typeBoth(`  ${KEY}  `, `\t${SECRET} `);
    fireEvent.click(submit());

    await waitFor(() => expect(puts(fetchMock)).toHaveLength(1));
    const init = (puts(fetchMock)[0] as [string, RequestInit])[1];
    // Exactly the two fields, both trimmed, with no label and no confirmation.
    expect(JSON.parse(String(init.body))).toEqual({ api_key: KEY, api_secret: SECRET });
  });

  it("asks Binance for two confirmations in a fieldset, both unticked, 44 px each, with the help that says only Enable Futures is rejected", () => {
    renderForm({ exchange: "binance", name: "Binance", confirmations: BINANCE_CONFIRMATIONS });

    const group = found(screen.queryByRole("group", { name: "What you checked in Binance" }), "the group");
    expect(group.tagName).toBe("FIELDSET");
    expect(group.querySelector("legend")).toHaveTextContent("What you checked in Binance");
    const boxes = within(group).queryAllByRole("checkbox");
    expect(boxes).toHaveLength(2);
    for (const [box, label] of [
      [boxes[0], WITHDRAWALS],
      [boxes[1], FUTURES],
    ] as const) {
      expect(box).not.toBeChecked();
      expect(box).toHaveAttribute("type", "checkbox");
      expect(box).toHaveAccessibleName(label);
      expect(box?.closest("label")).toHaveClass("min-h-11");
    }
    // "Rests on your word" is said once, about the withdrawal setting; Enable Futures is what the exchange rejects.
    expect(found(screen.queryByText(CONFIRM_HELP), "the confirmation help")).toHaveClass("text-ink-3");
    expect(CONFIRM_HELP).toMatch(/rejects the first live order/);
    expect(CONFIRM_HELP).toMatch(/Nothing checks the withdrawal setting: it rests on your word/);
  });

  it("test_binance_submit_sends_both_confirmations_true", async () => {
    const { fetchMock } = renderForm({ exchange: "binance", name: "Binance", confirmations: BINANCE_CONFIRMATIONS });
    typeBoth();
    tick(WITHDRAWALS);
    tick(FUTURES);

    fireEvent.click(submit());

    await waitFor(() => expect(puts(fetchMock)).toHaveLength(1));
    const [url, init] = puts(fetchMock)[0] as [string, RequestInit];
    expect(String(url)).toMatch(/\/credentials\/binance$/);
    expect(JSON.parse(String(init.body))).toEqual({
      api_key: KEY,
      api_secret: SECRET,
      withdrawals_disabled_confirmed: true,
      futures_enabled_confirmed: true,
    });
  });

  it("test_the_button_follows_what_is_typed", () => {
    renderForm();
    expect(submit()).toBeDisabled();

    fireEvent.change(keyField(), { target: { value: KEY } });
    expect(submit()).toBeDisabled();
    fireEvent.change(secretField(), { target: { value: SECRET } });
    expect(submit()).toBeEnabled();
    fireEvent.change(secretField(), { target: { value: "" } });
    expect(submit()).toBeDisabled();
    fireEvent.change(secretField(), { target: { value: SECRET } });
    fireEvent.change(keyField(), { target: { value: "" } });
    expect(submit()).toBeDisabled();
  });

  it("follows the boxes too: disabled until every box is ticked, disabled again when one is unticked", () => {
    renderForm({ exchange: "binance", name: "Binance", confirmations: BINANCE_CONFIRMATIONS });
    typeBoth();
    expect(submit()).toBeDisabled();

    tick(WITHDRAWALS);
    expect(submit()).toBeDisabled();
    tick(FUTURES);
    expect(submit()).toBeEnabled();
    tick(WITHDRAWALS);
    expect(submit()).toBeDisabled();
  });

  it("has a StatusButton of `Check and save` and `Checking…` that never reads Saved, and a Close that is never Cancel", () => {
    renderForm();

    const button = submit();
    expect(button).toHaveAttribute("type", "submit");
    expect(within(button).queryByText("Checking…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Checking…" })).not.toBeInTheDocument();
    const close = found(screen.queryByRole("button", { name: "Close" }), "Close");
    expect(close).toHaveAttribute("type", "button");
    expect(screen.queryByRole("button", { name: /Saved|Cancel/ })).not.toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toHaveLength(2);
  });

  it("calls onClose from Close", () => {
    const { props } = renderForm();

    fireEvent.click(found(screen.queryByRole("button", { name: "Close" }), "Close"));

    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it("submits on Enter through a <form noValidate> whose handler prevents the native submission", async () => {
    const { fetchMock } = renderForm();
    const form = formElement();
    expect(form.noValidate).toBe(true);
    typeBoth();

    const proceeded = fireEvent.submit(form);

    expect(proceeded).toBe(false);
    await waitFor(() => expect(puts(fetchMock)).toHaveLength(1));
  });

  it("sends nothing when the form is submitted with a field empty", async () => {
    const { fetchMock } = renderForm();
    fireEvent.change(keyField(), { target: { value: KEY } });

    fireEvent.submit(formElement());

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(puts(fetchMock)).toEqual([]);
  });

  it("puts the focus in API key when it opens", () => {
    renderForm();
    expect(keyField()).toHaveFocus();
  });

  it("has no amber and no hex colour or var() in any class", () => {
    renderForm({ exchange: "binance", name: "Binance", confirmations: BINANCE_CONFIRMATIONS, hasKey: true });
    const section = found(screen.queryByRole("region"), "the section");

    expect(section.outerHTML).not.toMatch(AMBER);
    for (const node of [section, ...Array.from(section.querySelectorAll("[class]"))]) {
      expect(node.className, node.tagName).not.toMatch(/#[0-9a-fA-F]{3,8}|var\(/);
    }
    expect(section.querySelector("[style]")).toBeNull();
  });
});

function answer(status: number, body: Record<string, unknown>): () => Promise<Response> {
  return () => Promise.resolve(jsonResponse(body, status));
}

const EMPTIED = "The fields were emptied. Enter the key again to retry.";
const SERVER_WORDING = "SERVER-WORDING-that-must-never-be-shown";

interface RefusalCase {
  reason: string;
  respond: () => Promise<Response>;
  text: string;
}

/** The fifteen texts of design § F, in English, with Bybit as the exchange (the Binance one below). */
const REFUSALS: RefusalCase[] = [
  {
    reason: "keyRejected",
    respond: answer(422, { outcome: "KEY_REJECTED", detail: SERVER_WORDING }),
    text: "Bybit did not accept this key. Check that the key and the secret were copied whole, that the key has not expired, and that it allows this server's IP address. Nothing was saved.",
  },
  {
    reason: "withdrawPermission",
    respond: answer(422, { outcome: "WITHDRAW_PERMISSION", detail: SERVER_WORDING }),
    text: "This key can take funds out of the account, so it was refused. Create a key without withdrawal permission and enter that one. Nothing was saved.",
  },
  {
    reason: "permissionsUnavailable",
    respond: answer(422, { outcome: "PERMISSIONS_UNAVAILABLE", detail: SERVER_WORDING }),
    text: "Bybit did not say what this key is allowed to do, so it was not saved. Try again in a moment.",
  },
  {
    reason: "venueUnreachable",
    respond: answer(502, { outcome: "VENUE_UNREACHABLE", detail: SERVER_WORDING }),
    text: "Bybit could not be reached, so the key was not checked and not saved. Nothing is known to be wrong with it. Try again.",
  },
  {
    reason: "concurrentSave",
    respond: answer(409, { outcome: "CONCURRENT_SAVE", detail: SERVER_WORDING }),
    text: "Another save for Bybit finished first, so this one was not stored. The card shows the key that is stored now. Check it before saving again.",
  },
  {
    reason: "confirmationRequiredUnlisted",
    respond: answer(422, { outcome: "CONFIRMATION_REQUIRED", detail: SERVER_WORDING, missing: ["not_a_known_name"] }),
    text: "The key was not saved, and nothing was sent to Bybit, because a confirmation is missing. Tick both and enter the key again.",
  },
  {
    reason: "confirmationNotApplicable",
    respond: answer(422, { outcome: "CONFIRMATION_NOT_APPLICABLE", detail: SERVER_WORDING }),
    text: "The panel sent a confirmation that Bybit does not take, so the key was not saved. Reload the page and enter the key again.",
  },
  {
    reason: "notServed",
    respond: answer(404, { detail: SERVER_WORDING }),
    text: "Bybit keys are not managed by this panel, so nothing was saved.",
  },
  {
    reason: "storageUnavailable",
    respond: answer(503, { detail: SERVER_WORDING }),
    text: "The server cannot store keys right now, so nothing was saved. If this repeats, the server's encryption key is missing or unusable and has to be fixed there.",
  },
  {
    reason: "invalidKey",
    respond: answer(422, { detail: [{ type: "string_too_short", loc: ["body", "api_key"], msg: SERVER_WORDING }] }),
    text: "The API key cannot be stored as typed. A key has 4 to 256 characters and no spaces or accented letters. Nothing was sent to Bybit.",
  },
  {
    reason: "invalidSecret",
    respond: answer(422, { detail: [{ type: "string_too_long", loc: ["body", "api_secret"], msg: SERVER_WORDING }] }),
    text: "The API secret cannot be stored as typed. A secret has at most 256 characters and no spaces or accented letters. Nothing was sent to Bybit.",
  },
  {
    reason: "invalidRequest",
    respond: answer(422, { detail: [{ type: "missing", loc: ["body"], msg: SERVER_WORDING }] }),
    text: "The server refused the request as malformed, so nothing was saved. Reload the page and enter the key again.",
  },
  {
    reason: "noAnswer",
    respond: () => Promise.reject(new TypeError(SERVER_WORDING)),
    text: "No answer came back from the server, so it is not known whether the key was saved. The card shows what is stored now.",
  },
  {
    reason: "unknown",
    respond: answer(500, { detail: SERVER_WORDING }),
    text: "The save ended in a way this panel cannot read (status 500), so it is not known whether the key was saved. The card shows what is stored now.",
  },
];

/** Types both fields and presses the button; the alert of the refusal is waited for as an assertion. */
async function refuseWith(respond: () => Promise<Response>, overrides: Partial<KeyEntryFormProps> = {}) {
  const rendered = renderForm(overrides, respond, true);
  typeBoth();
  for (const confirmation of overrides.confirmations ?? []) {
    tick(confirmation === "futures_enabled_confirmed" ? FUTURES : WITHDRAWALS);
  }
  fireEvent.click(submit());
  await waitFor(() => expect(screen.queryByRole("alert")).toBeInTheDocument());
  return rendered;
}

describe("the attempt: each answer shows its own text (design § F)", () => {
  it.each(REFUSALS)("test_each_answer_shows_its_own_text: $reason", async ({ respond, text }) => {
    await refuseWith(respond);

    const alert = found(screen.queryByRole("alert"), "the refusal");
    expect(alert).toHaveClass("text-loss");
    expect(alert).toHaveTextContent(text);
    // "The fields were emptied…" follows it, in ink-3, inside the same alert.
    expect(within(alert).queryByText(EMPTIED)).toHaveClass("text-ink-3");
    expect(alert.textContent).not.toContain(SERVER_WORDING);
  });

  it("names a missing confirmation by the checkbox's own label, one line per name", async () => {
    await refuseWith(
      answer(422, {
        outcome: "CONFIRMATION_REQUIRED",
        detail: SERVER_WORDING,
        missing: ["futures_enabled_confirmed", "withdrawals_disabled_confirmed"],
      }),
      { exchange: "binance", name: "Binance", confirmations: BINANCE_CONFIRMATIONS },
    );

    const alert = found(screen.queryByRole("alert"), "the refusal");
    expect(alert).toHaveTextContent(
      "The key was not saved, and nothing was sent to Binance, because a confirmation is missing:",
    );
    const lines = within(alert).queryAllByRole("listitem").map((item) => item.textContent);
    expect(lines).toEqual([FUTURES, WITHDRAWALS]);
  });

  it("test_a_missing_confirmation_is_named: one name gives one line", async () => {
    await refuseWith(
      answer(422, { outcome: "CONFIRMATION_REQUIRED", missing: ["futures_enabled_confirmed"] }),
      { exchange: "binance", name: "Binance", confirmations: BINANCE_CONFIRMATIONS },
    );

    expect(within(found(screen.queryByRole("alert"), "the refusal")).queryAllByRole("listitem").map((item) => item.textContent)).toEqual([FUTURES]);
  });

  it.each([
    ["names it does not know", ["something_else"]],
    ["a mix with an unknown name", ["futures_enabled_confirmed", "something_else"]],
    ["an empty list", []],
    ["not a list", "futures_enabled_confirmed"],
  ])("says confirmationRequiredUnlisted, with no lines, for a `missing` of %s", async (_label, missing) => {
    await refuseWith(
      answer(422, { outcome: "CONFIRMATION_REQUIRED", detail: SERVER_WORDING, missing }),
      { exchange: "binance", name: "Binance", confirmations: BINANCE_CONFIRMATIONS },
    );

    const alert = found(screen.queryByRole("alert"), "the refusal");
    expect(alert).toHaveTextContent(
      "The key was not saved, and nothing was sent to Binance, because a confirmation is missing. Tick both and enter the key again.",
    );
    expect(within(alert).queryAllByRole("listitem")).toEqual([]);
  });

  it("test_the_servers_wording_is_never_rendered", async () => {
    for (const { respond } of REFUSALS) {
      await refuseWith(respond);
      expect(document.body.textContent).not.toContain(SERVER_WORDING);
      cleanup();
    }
  });
});

describe("the attempt: what the form does after a refusal (design § F)", () => {
  it("keeps the form open, empties both fields and unticks the boxes, disables the button and moves the focus to API key", async () => {
    await refuseWith(answer(422, { outcome: "KEY_REJECTED" }), {
      exchange: "binance",
      name: "Binance",
      confirmations: BINANCE_CONFIRMATIONS,
    });

    expect(screen.queryByRole("heading", { level: 4, name: "Add a Binance key" })).toBeInTheDocument();
    expect(keyField().value).toBe("");
    expect(secretField().value).toBe("");
    for (const box of screen.getAllByRole("checkbox")) expect(box).not.toBeChecked();
    expect(submit()).toBeDisabled();
    expect(keyField()).toHaveFocus();
  });

  it("moves the focus back to API key from wherever it was", async () => {
    renderForm({}, answer(500, {}), true);
    typeBoth();
    secretField().focus();
    expect(secretField()).toHaveFocus();

    fireEvent.click(submit());

    await waitFor(() => expect(keyField()).toHaveFocus());
  });

  it("keeps the refusal while the owner types, removes it when the next attempt starts", async () => {
    let release: (response: Response) => void = () => undefined;
    const second = new Promise<Response>((resolve) => {
      release = resolve;
    });
    let calls = 0;
    renderForm({}, () => (++calls === 1 ? Promise.resolve(jsonResponse({ outcome: "KEY_REJECTED" }, 422)) : second), true);
    typeBoth();
    fireEvent.click(submit());
    await waitFor(() => expect(screen.queryByRole("alert")).toBeInTheDocument());

    fireEvent.change(keyField(), { target: { value: KEY } });
    fireEvent.change(secretField(), { target: { value: SECRET } });
    expect(screen.queryByRole("alert")).toBeInTheDocument();

    fireEvent.click(submit());
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    await act(async () => {
      release(jsonResponse(ANSWER));
    });
  });

  it("shows the refusal of a key that may have been stored, with the form open and emptied (noAnswer and unknown)", async () => {
    for (const reason of ["noAnswer", "unknown"]) {
      const { respond, text } = REFUSALS.find((entry) => entry.reason === reason) as RefusalCase;
      await refuseWith(respond);
      expect(screen.queryByRole("alert")).toHaveTextContent(text);
      expect(screen.queryByRole("alert")).toHaveTextContent("not known whether the key was saved");
      expect(keyField().value).toBe("");
      cleanup();
    }
  });
});

/** Every string under a key of a locale, with its path, whatever the depth. */
function flatten(value: unknown, path = ""): [string, string][] {
  if (typeof value === "string") return [[path, value]];
  if (typeof value !== "object" || value === null) return [];
  return Object.entries(value).flatMap(([key, child]) => flatten(child, path === "" ? key : `${path}.${key}`));
}

describe("the form in Spanish (spec: Every Settings Text Exists In English And Spanish)", () => {
  const english = flatten(en.settings.form);
  const spanish = new Map(flatten(es.settings.form));

  it("has every key of the form in both languages", () => {
    expect(english.length).toBeGreaterThanOrEqual(30);
    expect([...spanish.keys()].sort()).toEqual(english.map(([path]) => path).sort());
  });

  it("finds none of the English texts of the form, an open Binance form with its help, boxes and fieldset", async () => {
    await i18n.changeLanguage("es");
    renderForm({ exchange: "binance", name: "Binance", confirmations: BINANCE_CONFIRMATIONS, hasKey: true });

    const text = document.body.textContent ?? "";
    expect(screen.queryByRole("heading", { level: 4, name: "Reemplazar la clave de Binance" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Clave de API")).toBeInTheDocument();
    expect(screen.queryByLabelText("Secreto de API")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Lo que usted comprobó en Binance" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Comprobar y guardar" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cerrar" })).toBeInTheDocument();
    for (const [path, value] of english) {
      if (value.includes("{{") || spanish.get(path) === value) continue;
      expect(text, path).not.toContain(value);
    }
    // The help and the notes are the Spanish ones, with the exchange's name in them.
    expect(text).toContain("Antes de guardarla, la clave se prueba con una lectura real en Binance.");
    expect(text).toContain("Al guardar se reemplaza la clave guardada ahora");
    expect(text).toContain("Nada comprueba el ajuste de retiros: depende de lo que usted indique.");
  });

  it.each(REFUSALS)("says the refusal in Spanish, with no English text of it: $reason", async ({ reason, respond, text }) => {
    await i18n.changeLanguage("es");
    renderForm({}, respond, true);
    fireEvent.change(screen.getByLabelText("Clave de API"), { target: { value: KEY } });
    fireEvent.change(screen.getByLabelText("Secreto de API"), { target: { value: SECRET } });

    fireEvent.click(screen.getByRole("button", { name: "Comprobar y guardar" }));

    await waitFor(() => expect(screen.queryByRole("alert")).toBeInTheDocument());
    const spoken = found(screen.queryByRole("alert"), "the refusal").textContent ?? "";
    expect(spoken).not.toContain(text);
    expect(spoken).toContain("Los campos se vaciaron. Vuelva a introducir la clave para reintentar.");
    expect(spoken).not.toContain(EMPTIED);
    // It is the Spanish text of this reason, with the exchange's name or the status in it.
    const expected = es.settings.form.error[reason as keyof typeof es.settings.form.error] ?? "";
    expect(expected, reason).not.toBe("");
    expect(spoken).toContain(expected.replace("{{exchange}}", "Bybit").replace("{{status}}", "500"));
  });

  it("addresses the owner as usted in every text of the form, never as tu or vos", () => {
    const familiar =
      /\b(tú|tienes|puedes|debes|ingresa|inténtalo|querés|podés|vos|tenés|fijate|asegurate|volvé|creá|marcá|recargá)\b/i;
    for (const [path, value] of spanish) expect(value, path).not.toMatch(familiar);
    const imperatives = [...spanish.values()].join(" ");
    for (const usted of ["Compruebe", "Cree", "Marque", "Recargue", "Vuelva", "Inténtelo"]) {
      expect(imperatives, usted).toContain(usted);
    }
  });
});

describe("the attempt: while the request is in flight", () => {
  it("reads `Checking…`, is disabled, disables Close and makes the fields read-only", async () => {
    const { fetchMock } = renderForm({}, () => new Promise<Response>(() => undefined));
    typeBoth();

    fireEvent.click(submit());

    await waitFor(() => expect(puts(fetchMock)).toHaveLength(1));
    const button = found(screen.queryByRole<HTMLButtonElement>("button", { name: "Checking…" }), "Checking…");
    expect(button).toBeDisabled();
    expect(found(screen.queryByRole("button", { name: "Close" }), "Close")).toBeDisabled();
    expect(keyField()).toHaveAttribute("readonly");
    expect(secretField()).toHaveAttribute("readonly");
  });

  it("tells the page when an attempt starts and when it ends", async () => {
    const { props } = renderForm({}, answer(500, {}));
    typeBoth();

    fireEvent.click(submit());

    await waitFor(() => expect(props.onBusyChange).toHaveBeenLastCalledWith(false));
    expect(props.onBusyChange).toHaveBeenNthCalledWith(1, true);
    expect(props.onBusyChange).toHaveBeenCalledTimes(2);
  });
});

describe("the attempt: what is read again and what the page is told", () => {
  it.each([
    ["a save that worked", answer(200, ANSWER)],
    ["a refusal", answer(422, { outcome: "KEY_REJECTED" })],
    ["an unreadable answer", answer(500, {})],
    ["a network failure", () => Promise.reject(new TypeError("offline"))],
  ])("reads both lists again after %s", async (_label, respond) => {
    const { fetchMock } = renderForm({}, respond, true);
    await waitFor(() => expect(listReads(fetchMock)).toHaveLength(2));
    typeBoth();

    fireEvent.click(submit());

    await waitFor(() => expect(listReads(fetchMock)).toHaveLength(4));
    const urls = listReads(fetchMock).map(([url]) => String(url).replace(/^.*\/api/, ""));
    expect(urls.filter((url) => url === "/credentials")).toHaveLength(2);
    expect(urls.filter((url) => url === "/pools")).toHaveLength(2);
  });

  it("reads nothing again after a 401", async () => {
    const { fetchMock } = renderForm({}, answer(401, { detail: SERVER_WORDING }), true);
    await waitFor(() => expect(listReads(fetchMock)).toHaveLength(2));
    typeBoth();

    fireEvent.click(submit());

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 40));
    });
    expect(puts(fetchMock)).toHaveLength(1);
    expect(listReads(fetchMock)).toHaveLength(2);
  });

  it("hands `{last4, readOnly}` to the page once for a save that worked, and nothing for a refusal", async () => {
    const saved = renderForm({}, answer(200, ANSWER));
    typeBoth();
    fireEvent.click(submit());
    await waitFor(() => expect(saved.props.onSaved).toHaveBeenCalledTimes(1));
    expect(saved.props.onSaved).toHaveBeenCalledWith({ last4: "Z9y8", readOnly: false });
    cleanup();

    const refused = renderForm({}, answer(422, { outcome: "KEY_REJECTED" }));
    typeBoth();
    fireEvent.click(submit());
    await waitFor(() => expect(screen.queryByRole("alert")).toBeInTheDocument());
    expect(refused.props.onSaved).not.toHaveBeenCalled();
  });

  it("says that the key cannot trade when the answer's warnings say so", async () => {
    const { props } = renderForm({}, answer(200, { ...ANSWER, warnings: ["READ_ONLY_KEY"] }));
    typeBoth();

    fireEvent.click(submit());

    await waitFor(() => expect(props.onSaved).toHaveBeenCalledWith({ last4: "Z9y8", readOnly: true }));
  });

  it("still reads both lists again, but records nothing and focuses nothing, when the form was taken out of the document meanwhile", async () => {
    let release: (response: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const { fetchMock, props, rerenderWithoutForm } = renderForm({}, () => pending, true);
    await waitFor(() => expect(listReads(fetchMock)).toHaveLength(2));
    typeBoth();
    fireEvent.click(submit());
    await waitFor(() => expect(puts(fetchMock)).toHaveLength(1));
    const outside = document.createElement("button");
    document.body.append(outside);
    outside.focus();

    rerenderWithoutForm();
    await act(async () => {
      release(jsonResponse(ANSWER));
      await new Promise((resolve) => setTimeout(resolve, 30));
    });

    // The owner left the page during the check, and the exchange tabs of the page
    // they went to read the keys BEFORE the save ended. Without this re-read a tab
    // would go on saying `no key` about an exchange whose key was just stored.
    const urls = listReads(fetchMock).map(([url]) => String(url).replace(/^.*\/api/, ""));
    expect(urls).toHaveLength(4);
    expect(urls.filter((url) => url === "/credentials")).toHaveLength(2);
    expect(urls.filter((url) => url === "/pools")).toHaveLength(2);
    expect(props.onSaved).not.toHaveBeenCalled();
    expect(outside).toHaveFocus();
    expect(props.onBusyChange).toHaveBeenLastCalledWith(false);
  });
});
