import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KeyEntryForm, type KeyEntryFormProps } from "@/features/settings/KeyEntryForm";
import i18n from "@/shared/i18n";
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
}

/** The form alone, on its own query client, with the `PUT` of its exchange answered by `respond`. */
function renderForm(
  overrides: Partial<KeyEntryFormProps> = {},
  respond: () => Promise<Response> = () => Promise.resolve(jsonResponse(ANSWER)),
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
  render(
    <QueryClientProvider client={queryClient}>
      <KeyEntryForm {...props} />
    </QueryClientProvider>,
  );
  return { props, queryClient, fetchMock };
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
