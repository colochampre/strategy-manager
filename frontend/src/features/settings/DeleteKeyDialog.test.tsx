import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DeleteKeyControl } from "@/features/settings/DeleteKeyControl";
import { type ExtraRoute, jsonResponse, lock, pool, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const LAST4 = "7Q2d";
const DETAIL = "SERVER-DETAIL-SENTINEL: the text the server wrote";

const TITLE = "Delete the Bybit key?";
const BODY = `The key ending in ${LAST4} is removed from this system. Bybit is no longer read or traded from here until a key is added again. Its history stays.`;
const CONDITION = "The server allows this only while every Bybit strategy is disabled and nothing is open on it.";
const NOT_FLAT = "The Bybit key cannot be deleted yet. This is in the way:";
const UNLISTED =
  "The Bybit key cannot be deleted yet: a strategy is still enabled, a position is open or an order is in progress.";
const GONE = "The server found no Bybit key to delete. Close this: the card shows what is stored now.";
const UNKNOWN =
  "The delete ended in a way this panel cannot read. Close this: the card shows whether the key is still stored.";

const REFUSAL = {
  outcome: "EXCHANGE_NOT_FLAT",
  detail: DETAIL,
  enabled_strategies: [
    { id: "s-1", name: "Alpha" },
    { id: "s-2", name: "Beta" },
  ],
  symbols: ["STXUSDT.P", "BTCUSDT"],
  allocations: ["alloc-1", "alloc-2", "alloc-3"],
  live_reservations: [],
  in_flight_attempts: ["attempt-1"],
};

const showModal = vi.fn(function (this: HTMLDialogElement) {
  this.setAttribute("open", "");
});
const close = vi.fn(function (this: HTMLDialogElement) {
  this.removeAttribute("open");
});

beforeEach(() => {
  unlock();
  showModal.mockClear();
  close.mockClear();
  // jsdom has no `showModal` or `close`; the dialog upgrades itself where they exist.
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, writable: true, value: showModal });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, writable: true, value: close });
});
afterEach(() => {
  Reflect.deleteProperty(HTMLDialogElement.prototype, "showModal");
  Reflect.deleteProperty(HTMLDialogElement.prototype, "close");
  vi.unstubAllGlobals();
  lock();
});

type Answer = () => Promise<Response>;
const answers = (status: number, body: unknown): Answer => () => Promise.resolve(jsonResponse(body, status));
const never: Answer = () => new Promise<Response>(() => undefined);

/** The control alone, with the `DELETE` answered by the test and every request counted. */
function mount(onDelete: Answer = answers(200, { exchange: "bybit" })) {
  const extra: ExtraRoute = (url, init) =>
    url.endsWith("/credentials/bybit") && init?.method === "DELETE" ? onDelete() : undefined;
  const fetchMock = stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit")] }, {}, extra);
  const onDeleted = vi.fn();
  const onOpen = vi.fn();
  const onFocusFallback = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <DeleteKeyControl
        exchange="bybit"
        name="Bybit"
        last4={LAST4}
        onDeleted={onDeleted}
        onOpen={onOpen}
        onFocusFallback={onFocusFallback}
      />
    </QueryClientProvider>,
  );
  return { fetchMock, onDeleted, onOpen, onFocusFallback };
}

function deletes(fetchMock: ReturnType<typeof stubApi>) {
  return fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE");
}

function opener(): HTMLElement {
  const button = screen.queryByRole("button", { name: "Delete key Bybit" });
  expect(button).toBeInTheDocument();
  return button as HTMLElement;
}

function dialogEl(): HTMLElement {
  const dialog = screen.queryByRole("dialog", { name: TITLE });
  expect(dialog).toBeInTheDocument();
  return dialog as HTMLElement;
}

function openDialog(): HTMLElement {
  fireEvent.click(opener());
  return dialogEl();
}

function cancelButton(): HTMLElement {
  const button = within(dialogEl()).queryByRole("button", { name: "Cancel" });
  expect(button).toBeInTheDocument();
  return button as HTMLElement;
}

function confirmButton(name: "Delete key" | "Deleting…" = "Delete key"): HTMLElement {
  const button = within(dialogEl()).queryByRole("button", { name });
  expect(button).toBeInTheDocument();
  return button as HTMLElement;
}

async function confirm() {
  fireEvent.click(confirmButton());
  // A macrotask: the mutation reports `pending` a few microtasks after the click.
  await act(async () => {
    await new Promise((done) => setTimeout(done, 0));
  });
}

describe("the dialog's shape (spec: deleting a key is confirmed with a plain button)", () => {
  it("is a native dialog opened with showModal, named by its title, and not open before the click", () => {
    mount();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(showModal).not.toHaveBeenCalled();

    const dialog = openDialog();

    expect(dialog.tagName).toBe("DIALOG");
    expect(showModal).toHaveBeenCalledTimes(1);
    const titleId = dialog.getAttribute("aria-labelledby");
    expect(titleId).not.toBeNull();
    expect(document.getElementById(titleId as string)).toHaveTextContent(TITLE);
  });

  it("says the key's last four, what leaves this system, and what the server allows, word for word", () => {
    mount();

    const dialog = openDialog();

    expect(within(dialog).queryByText(BODY)).toBeInTheDocument();
    expect(within(dialog).queryByText(CONDITION)).toBeInTheDocument();
    // The hint is the last four characters and nothing more of the key.
    expect(dialog.textContent).toContain(LAST4);
  });

  it("has Cancel then Delete key, in that order in the document, and no other button", () => {
    mount();

    const dialog = openDialog();

    expect(within(dialog).getAllByRole("button").map((button) => button.textContent)).toEqual(["Cancel", "Delete key"]);
  });

  it("draws Cancel outlined and Delete key filled in loss, both at least 44 px tall", () => {
    mount();
    openDialog();

    const cancel = cancelButton();
    const remove = confirmButton();

    expect(cancel).toHaveClass("min-h-11");
    expect(remove).toHaveClass("min-h-11");
    expect(cancel).toHaveClass("border-rule");
    expect(cancel.className).not.toMatch(/\bbg-loss\b/);
    expect(remove).toHaveClass("bg-loss");
  });

  it("gives the focus to Cancel when it opens: the safe button", () => {
    mount();
    openDialog();

    expect(cancelButton()).toHaveFocus();
  });

  it("test_the_confirmation_is_a_plain_button: nothing to type", () => {
    mount();

    const dialog = openDialog();

    expect(dialog.querySelector("input, textarea, select, [contenteditable]")).toBeNull();
    expect(within(dialog).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("form")).not.toBeInTheDocument();
  });
});

describe("what sends the request, and what never does", () => {
  it("test_delete_requires_explicit_confirmation_not_single_click: the click that opens the dialog sends nothing", async () => {
    const { fetchMock } = mount();

    fireEvent.click(opener());
    await act(async () => {
      await Promise.resolve();
    });

    expect(deletes(fetchMock)).toHaveLength(0);
    expect(dialogEl()).toBeInTheDocument();
  });

  it("sends exactly one DELETE, from the dialog's own button", async () => {
    const { fetchMock } = mount();
    openDialog();

    await confirm();

    expect(deletes(fetchMock)).toHaveLength(1);
    expect(String(deletes(fetchMock)[0]?.[0])).toMatch(/\/credentials\/bybit$/);
  });

  it("sends nothing on Cancel, Escape or the browser's cancel event, and closes", async () => {
    const { fetchMock, onFocusFallback } = mount();

    openDialog();
    fireEvent.click(cancelButton());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    const second = openDialog();
    fireEvent.keyDown(second, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    const third = openDialog();
    fireEvent(third, new Event("cancel", { cancelable: true }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    expect(deletes(fetchMock)).toHaveLength(0);
    // The card still holds `Delete key`, so the control takes the focus back itself.
    expect(opener()).toHaveFocus();
    expect(onFocusFallback).not.toHaveBeenCalled();
  });

  it("draws an aria-hidden Trash on the confirm, kept while it says Deleting…, and none on Cancel", async () => {
    mount(never);
    openDialog();

    const svg = confirmButton().querySelector("svg");
    expect(svg).toHaveClass("lucide-trash", "size-4", "shrink-0");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(confirmButton().firstElementChild).toBe(svg);
    expect(confirmButton()).toHaveClass("inline-flex", "items-center", "gap-1.5");
    expect(cancelButton().querySelector("svg")).toBeNull();

    await confirm();

    expect(confirmButton("Deleting…").querySelector("svg")).toHaveClass("lucide-trash");
  });

  it("test_the_dialog_cannot_be_dismissed_mid_request: Deleting…, both buttons off, Escape and cancel do nothing, one request", async () => {
    const { fetchMock } = mount(never);
    const dialog = openDialog();

    await confirm();

    const pending = confirmButton("Deleting…");
    expect(pending).toBeDisabled();
    expect(cancelButton()).toBeDisabled();
    fireEvent.keyDown(dialog, { key: "Escape" });
    fireEvent(dialog, new Event("cancel", { cancelable: true }));
    fireEvent.click(cancelButton());
    fireEvent.click(pending);
    fireEvent.click(pending);
    await act(async () => {
      await Promise.resolve();
    });

    expect(dialogEl()).toBeInTheDocument();
    expect(deletes(fetchMock)).toHaveLength(1);
  });

  it("never retries by itself: a failed delete is one request, however long the dialog stays open", async () => {
    vi.useFakeTimers();
    try {
      const { fetchMock } = mount(answers(500, { detail: DETAIL }));
      openDialog();
      fireEvent.click(confirmButton());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });

      expect(deletes(fetchMock)).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("what the dialog says for each answer", () => {
  it("test_a_refused_delete_states_why_and_keeps_the_key: a line per kind that has entries, in loss, as an alert", async () => {
    const { fetchMock, onDeleted } = mount(answers(409, REFUSAL));
    const dialog = openDialog();

    await confirm();

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveClass("text-loss");
    expect(alert).toHaveTextContent(NOT_FLAT);
    const lines = within(alert).getAllByRole("listitem").map((line) => line.textContent);
    expect(lines).toEqual([
      "2 enabled strategies: Alpha, Beta. Disable them first.",
      "Open position on: STXUSDT.P, BTCUSDT. It has to be closed first.",
      "3 open allocations. They end when their positions are closed.",
      "1 order being placed right now. Wait for it to finish, then try again.",
    ]);
    // The ids are counted, never listed; the names are text, not links; the server's wording is not shown.
    expect(dialog.textContent).not.toContain("alloc-1");
    expect(dialog.textContent).not.toContain("attempt-1");
    expect(dialog.textContent).not.toContain(DETAIL);
    expect(dialog.querySelector("a")).toBeNull();
    // Both buttons stay, enabled, and the dialog stays open.
    expect(confirmButton()).toBeEnabled();
    expect(cancelButton()).toBeEnabled();
    expect(onDeleted).not.toHaveBeenCalled();
    expect(deletes(fetchMock)).toHaveLength(1);
  });

  it("sends a second request on a second Delete key press after a refusal, and only then", async () => {
    const { fetchMock } = mount(answers(409, REFUSAL));
    openDialog();
    await confirm();
    await screen.findByRole("alert");
    expect(deletes(fetchMock)).toHaveLength(1);

    await confirm();

    await waitFor(() => expect(deletes(fetchMock)).toHaveLength(2));
  });

  it("uses the singular line for a count of one, and the plural for more, in the design's words", async () => {
    mount(
      answers(409, {
        ...REFUSAL,
        enabled_strategies: [{ id: "s-1", name: "Alpha" }],
        symbols: [],
        allocations: ["alloc-1"],
        live_reservations: ["res-1", "res-2"],
        in_flight_attempts: ["attempt-1", "attempt-2", "attempt-3"],
      }),
    );
    openDialog();

    await confirm();

    const alert = await screen.findByRole("alert");
    expect(within(alert).getAllByRole("listitem").map((line) => line.textContent)).toEqual([
      "1 enabled strategy: Alpha. Disable it first.",
      "1 open allocation. It ends when its position is closed.",
      "2 live reservations: capital held for orders. Wait for them to finish, then try again.",
      "3 orders being placed right now. Wait for them to finish, then try again.",
    ]);
  });

  it("uses the singular reservation line for a count of one", async () => {
    mount(answers(409, { ...REFUSAL, live_reservations: ["res-1"], in_flight_attempts: [] }));
    openDialog();

    await confirm();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("1 live reservation: capital held for an order. Wait for it to finish, then try again.");
  });

  it("test_never_half_a_list: a refusal whose lists cannot all be read says it in general words and lists nothing", async () => {
    const { enabled_strategies: _gone, ...partial } = REFUSAL;
    mount(answers(409, partial));
    const dialog = openDialog();

    await confirm();

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent(UNLISTED);
    expect(alert).toHaveClass("text-loss");
    expect(within(dialog).queryAllByRole("listitem")).toHaveLength(0);
    expect(dialog.textContent).not.toContain("This is in the way");
    expect(dialog.textContent).not.toContain("STXUSDT.P");
    expect(dialog.textContent).not.toContain(DETAIL);
  });

  it("test_a_404_is_not_a_success: says the server found no key, and reports nothing deleted", async () => {
    const { onDeleted } = mount(answers(404, { detail: DETAIL }));
    const dialog = openDialog();

    await confirm();

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent(GONE);
    expect(dialog.textContent).not.toContain(DETAIL);
    expect(onDeleted).not.toHaveBeenCalled();
    expect(screen.queryByText(/key deleted/)).not.toBeInTheDocument();
    expect(dialogEl()).toBeInTheDocument();
  });

  it.each([
    ["a 500", answers(500, { detail: DETAIL })],
    ["no answer", (() => Promise.reject(new TypeError("offline"))) as Answer],
    ["a 409 that is not the refusal the panel knows", answers(409, { outcome: "SOMETHING_ELSE", detail: DETAIL })],
  ])("test_a_delete_with_no_readable_answer_says_the_key_may_be_gone: %s", async (_label, answer) => {
    const { onDeleted } = mount(answer);
    const dialog = openDialog();

    await confirm();

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent(UNKNOWN);
    expect(alert).toHaveClass("text-loss");
    expect(dialog.textContent).not.toContain(DETAIL);
    expect(onDeleted).not.toHaveBeenCalled();
  });

  it("leaves a 401 to the token gate: the dialog says nothing and reports nothing", async () => {
    const { fetchMock, onDeleted } = mount(answers(401, { detail: DETAIL }));
    const dialog = openDialog();

    await confirm();

    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
    expect(dialog.textContent).not.toContain(DETAIL);
    expect(onDeleted).not.toHaveBeenCalled();
    expect(deletes(fetchMock)).toHaveLength(1);
  });

  it("closes on a delete that worked and reports it once", async () => {
    const { fetchMock, onDeleted } = mount(answers(200, { exchange: "bybit" }));
    openDialog();

    await confirm();

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(onDeleted).toHaveBeenCalledTimes(1);
    expect(deletes(fetchMock)).toHaveLength(1);
  });
});
