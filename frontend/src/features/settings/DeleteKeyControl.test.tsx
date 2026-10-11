import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import { SettingsPage } from "@/features/settings/SettingsPage";
import i18n from "@/shared/i18n";
import {
  type ExtraRoute,
  emptyKey,
  jsonResponse,
  lock,
  pool,
  renderAt,
  resetExchangeScope,
  storedKey,
  stubApi,
  unlock,
} from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const OLD_LAST4 = "1234";
const NEW_LAST4 = "7Q2d";
const DELETED_STATUS = "Bybit key deleted.";
const SAVED_NOTICE = `Key ending in ${NEW_LAST4} saved.`;
const DETAIL = "SERVER-DETAIL-SENTINEL";
const REFUSAL = {
  outcome: "EXCHANGE_NOT_FLAT",
  detail: DETAIL,
  enabled_strategies: [{ id: "s-1", name: "Alpha" }],
  symbols: [],
  allocations: [],
  live_reservations: [],
  in_flight_attempts: [],
};

const showModal = vi.fn(function (this: HTMLDialogElement) {
  this.setAttribute("open", "");
});
const close = vi.fn(function (this: HTMLDialogElement) {
  this.removeAttribute("open");
});

beforeEach(() => {
  unlock();
  resetExchangeScope();
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, writable: true, value: showModal });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, writable: true, value: close });
});
afterEach(async () => {
  Reflect.deleteProperty(HTMLDialogElement.prototype, "showModal");
  Reflect.deleteProperty(HTMLDialogElement.prototype, "close");
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

const disabledPool = (exchange: string) => ({ ...pool(exchange), enabled: false });

interface Setup {
  /** The list before anything happens. */
  credentials?: unknown[];
  /** The list once the server has deleted the key (`serverDeletes`). */
  afterDelete?: unknown[];
  /** The list once a save worked. */
  afterSave?: unknown[];
  poolsBefore?: unknown[];
  poolsAfter?: unknown[];
  /** What the `DELETE` answers. */
  onDelete?: () => Promise<Response>;
  /** Whether the server deletes the key whatever it answers (a lost answer after a delete that worked). */
  serverDeletes?: boolean;
  /** Render the whole app (so the tabs and the navigation exist) instead of the page alone. */
  shell?: boolean;
}

/** Settings with the delete wired: the `DELETE` answered by the test, and the lists changing when the server deletes. */
function deletePage({
  credentials = [storedKey("bybit", { last4: OLD_LAST4 }), emptyKey("binance")],
  afterDelete = [emptyKey("bybit"), emptyKey("binance")],
  afterSave = [storedKey("bybit", { last4: NEW_LAST4 }), emptyKey("binance")],
  poolsBefore = [pool("bybit")],
  poolsAfter = [disabledPool("bybit")],
  onDelete = () => Promise.resolve(jsonResponse({ exchange: "bybit" })),
  serverDeletes = true,
  shell = false,
}: Setup = {}) {
  const state = { deleted: false, saved: false };
  const extra: ExtraRoute = (url, init) => {
    const method = init?.method ?? "GET";
    if (url.endsWith("/credentials/bybit") && method === "DELETE") {
      if (serverDeletes) state.deleted = true;
      return onDelete();
    }
    if (url.endsWith("/credentials/bybit") && method === "PUT") {
      state.saved = true;
      return Promise.resolve(jsonResponse({ exchange: "bybit", last4: NEW_LAST4, warnings: [], facts: { trade_capable: true } }));
    }
    if (url.endsWith("/credentials") && method === "GET") {
      return Promise.resolve(jsonResponse(state.deleted ? afterDelete : state.saved ? afterSave : credentials));
    }
    if (url.endsWith("/pools") && method === "GET") {
      return Promise.resolve(jsonResponse(state.deleted ? poolsAfter : poolsBefore));
    }
    return undefined;
  };
  const fetchMock = stubApi(HEALTH, [], { kind: "ok", body: poolsBefore }, {}, extra, {}, { kind: "ok", body: credentials });
  if (shell) renderAt(<AppRoutes />, "/settings");
  else {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={["/settings"]}>
          <SettingsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }
  return { fetchMock, state };
}

async function cardsDrawn() {
  await waitFor(() => expect(screen.queryAllByRole("article").length).toBeGreaterThan(0));
}

const card = (name: string) => screen.getByRole("article", { name });
const deleteButton = (name = "Bybit") => screen.queryByRole("button", { name: `Delete key ${name}` });

function present(element: HTMLElement | null): HTMLElement {
  expect(element).toBeInTheDocument();
  return element as HTMLElement;
}

function requests(fetchMock: ReturnType<typeof stubApi>, method: string) {
  return fetchMock.mock.calls.filter(([, init]) => (init?.method ?? "GET") === method);
}

async function confirmDelete() {
  fireEvent.click(present(deleteButton()));
  const dialog = present(screen.queryByRole("dialog"));
  fireEvent.click(within(dialog).getByRole("button", { name: "Delete key" }));
}

describe("where Delete key is drawn (spec: operable by keyboard and named for assistive technology)", () => {
  it("is on a served card with a stored key, and never on a card without a key or one the panel does not manage", async () => {
    deletePage({
      credentials: [storedKey("bybit", { last4: OLD_LAST4 }), emptyKey("binance"), storedKey("pionex")],
      poolsBefore: [pool("bybit"), pool("pionex", "spot")],
    });
    await cardsDrawn();

    expect(deleteButton("Bybit")).toBeInTheDocument();
    expect(deleteButton("Binance")).not.toBeInTheDocument();
    expect(deleteButton("Pionex")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("button", { name: /^Delete key/ })).toHaveLength(1);
  });

  it("is outlined in loss, 44 px, named with its exchange, and enabled when shown", async () => {
    deletePage();
    await cardsDrawn();

    const button = present(deleteButton());
    expect(button).toHaveAccessibleName("Delete key Bybit");
    expect(button).toHaveTextContent("Delete key");
    expect(button).toHaveClass("min-h-11", "border-loss", "text-loss");
    expect(button.className).not.toMatch(/\bbg-loss\b/);
    expect(button).toBeEnabled();
  });

  it("is disabled while that card's form is open, and only that card's", async () => {
    deletePage({ credentials: [storedKey("bybit", { last4: OLD_LAST4 }), storedKey("binance")], poolsBefore: [pool("bybit"), pool("binance")] });
    await cardsDrawn();
    expect(present(deleteButton("Bybit"))).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Replace key Bybit" }));

    expect(present(deleteButton("Bybit"))).toBeDisabled();
    expect(present(deleteButton("Binance"))).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(present(deleteButton("Bybit"))).toBeEnabled());
  });

  it("sits after the toggle and before the form in the card", async () => {
    deletePage();
    await cardsDrawn();
    fireEvent.click(screen.getByRole("button", { name: "Replace key Bybit" }));

    const toggle = screen.getByRole("button", { name: "Replace key Bybit" });
    const remove = present(deleteButton());
    const form = screen.getByLabelText("API key");
    expect(toggle.compareDocumentPosition(remove) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(remove.compareDocumentPosition(form) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe("opening and closing the dialog", () => {
  it("one click only opens the dialog: no request of any kind is written", async () => {
    const { fetchMock } = deletePage();
    await cardsDrawn();

    fireEvent.click(present(deleteButton()));

    expect(screen.queryByRole("dialog", { name: "Delete the Bybit key?" })).toBeInTheDocument();
    expect(requests(fetchMock, "DELETE")).toHaveLength(0);
    expect(requests(fetchMock, "PUT")).toHaveLength(0);
  });

  it("returns the focus to Delete key when Cancel or Escape closes it", async () => {
    deletePage();
    await cardsDrawn();

    fireEvent.click(present(deleteButton()));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(present(deleteButton())).toHaveFocus();

    fireEvent.click(present(deleteButton()));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(present(deleteButton())).toHaveFocus();
  });

  it("test_the_notice_of_an_earlier_save_is_gone_once_the_delete_dialog_opens", async () => {
    deletePage();
    await cardsDrawn();
    fireEvent.click(screen.getByRole("button", { name: "Replace key Bybit" }));
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "FAKE-key-0001" } });
    fireEvent.change(screen.getByLabelText("API secret"), { target: { value: "FAKE-secret-0002" } });
    fireEvent.click(screen.getByRole("button", { name: "Check and save" }));
    await waitFor(() => expect(within(card("Bybit")).queryByText(SAVED_NOTICE)).toBeInTheDocument());
    await waitFor(() => expect(deleteButton()).toBeInTheDocument());
    expect(screen.getAllByRole("status").some((region) => region.textContent === SAVED_NOTICE)).toBe(true);

    fireEvent.click(present(deleteButton()));

    expect(within(card("Bybit")).queryByText(SAVED_NOTICE)).not.toBeInTheDocument();
    expect(screen.getAllByRole("status").some((region) => region.textContent === SAVED_NOTICE)).toBe(false);
  });
});

describe("the end of a delete that worked (spec: the empty state is the one of a key never configured)", () => {
  it("closes the dialog on a card that is already the new one, says it in the status region and focuses Add key", async () => {
    deletePage();
    await cardsDrawn();

    await confirmDelete();

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // The lists were read again before the dialog closed: the card behind it is the new one at once.
    expect(screen.queryByRole("button", { name: "Add key Bybit" })).toBeInTheDocument();
    expect(deleteButton()).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(OLD_LAST4);

    const status = present(screen.queryByText(DELETED_STATUS));
    expect(status).toHaveAttribute("role", "status");
    expect(status).toHaveClass("sr-only");
    expect(status.closest("article")).toBeNull();
    await waitFor(() => expect(screen.getByRole("button", { name: "Add key Bybit" })).toHaveFocus());
  });

  it("test_confirmed_successful_delete_shows_same_empty_state_as_never_configured: the card's markup is the same", async () => {
    deletePage();
    await cardsDrawn();
    await confirmDelete();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Add key Bybit" })).toBeInTheDocument());
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // Ids come from the order of rendering; what is compared is the markup.
    const normalise = (html: string) => html.replace(/\b(id|aria-labelledby|aria-controls|for)="[^"]*"/g, '$1=""');
    const afterDelete = normalise(card("Bybit").innerHTML);
    cleanup();

    deletePage({
      credentials: [emptyKey("bybit"), emptyKey("binance")],
      poolsBefore: [disabledPool("bybit")],
    });
    await cardsDrawn();
    const neverConfigured = normalise(card("Bybit").innerHTML);

    expect(afterDelete).toContain("Add key");
    expect(afterDelete).toBe(neverConfigured);
  });

  it("makes that exchange's tab read `no key` in grey", async () => {
    deletePage({ shell: true });
    await cardsDrawn();
    await confirmDelete();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    fireEvent.click(screen.getAllByRole("link", { name: "Overview" })[0] as HTMLElement);

    const tabs = await screen.findAllByRole("button", { name: "bybit no key" });
    const mark = within(tabs[0] as HTMLElement).getByText("no key");
    expect(mark).toHaveClass("text-ink-3");
    expect(mark).not.toHaveClass("text-decision");
  });
});

describe("a delete that did not work leaves the card telling the truth", () => {
  it("test_a_refused_delete_keeps_the_key: the card still shows it, the lists were read again, nothing is announced", async () => {
    const { fetchMock } = deletePage({
      onDelete: () => Promise.resolve(jsonResponse(REFUSAL, 409)),
      serverDeletes: false,
    });
    await cardsDrawn();
    const readsBefore = requests(fetchMock, "GET").filter(([url]) => String(url).endsWith("/credentials")).length;

    await confirmDelete();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The Bybit key cannot be deleted yet. This is in the way:");
    await waitFor(() =>
      expect(requests(fetchMock, "GET").filter(([url]) => String(url).endsWith("/credentials")).length).toBeGreaterThan(readsBefore),
    );
    expect(screen.queryByRole("dialog")).toBeInTheDocument();
    expect(present(deleteButton())).toBeInTheDocument();
    expect(card("Bybit")).toHaveTextContent(OLD_LAST4);
    expect(screen.queryByText(DELETED_STATUS)).not.toBeInTheDocument();
  });

  it("test_a_lost_answer_after_a_delete_that_worked: the dialog says it is not known, and the card behind it shows no key", async () => {
    deletePage({ onDelete: () => Promise.resolve(jsonResponse({ detail: DETAIL }, 500)), serverDeletes: true });
    await cardsDrawn();

    await confirmDelete();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The delete ended in a way this panel cannot read.");
    await waitFor(() => expect(screen.queryByRole("button", { name: "Add key Bybit" })).toBeInTheDocument());
    expect(deleteButton()).not.toBeInTheDocument();
    expect(screen.queryByText(DELETED_STATUS)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(DETAIL);

    // `Delete key` is gone, so the page takes the focus to the card's toggle.
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Add key Bybit" })).toHaveFocus());
  });

  it("test_a_delete_whose_page_left_still_reads_both_lists_again", async () => {
    let release: (response: Response) => void = () => undefined;
    const held = new Promise<Response>((done) => {
      release = done;
    });
    const { fetchMock } = deletePage({ shell: true, onDelete: () => held });
    await cardsDrawn();
    await confirmDelete();
    await waitFor(() => expect(requests(fetchMock, "DELETE")).toHaveLength(1));

    fireEvent.click(screen.getAllByRole("link", { name: "Overview" })[0] as HTMLElement);
    await waitFor(() => expect(screen.queryByRole("article")).not.toBeInTheDocument());
    const mark = fetchMock.mock.calls.length;
    release(jsonResponse({ exchange: "bybit" }));

    const after = () => fetchMock.mock.calls.slice(mark).map(([url]) => String(url));
    await waitFor(() => expect(after().some((url) => url.endsWith("/credentials"))).toBe(true));
    await waitFor(() => expect(after().some((url) => url.endsWith("/pools"))).toBe(true));
  });
});

describe("the requests of a session (spec: the panel reads the two routes and writes through the two)", () => {
  it("test_the_requests_are_two_reads_and_one_put_and_one_delete", async () => {
    const { fetchMock } = deletePage();
    await cardsDrawn();

    fireEvent.click(screen.getByRole("button", { name: "Replace key Bybit" }));
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "FAKE-key-0001" } });
    fireEvent.change(screen.getByLabelText("API secret"), { target: { value: "FAKE-secret-0002" } });
    fireEvent.click(screen.getByRole("button", { name: "Check and save" }));
    await waitFor(() => expect(requests(fetchMock, "PUT")).toHaveLength(1));
    await waitFor(() => expect(deleteButton()).toBeInTheDocument());
    await confirmDelete();
    await waitFor(() => expect(screen.queryByText(DELETED_STATUS)).toBeInTheDocument());

    const seen = new Set(
      fetchMock.mock.calls.map(([url, init]) => `${init?.method ?? "GET"} ${String(url).replace(/^.*\/api/, "")}`),
    );
    expect([...seen].sort()).toEqual(
      ["DELETE /credentials/bybit", "GET /credentials", "GET /pools", "PUT /credentials/bybit"].sort(),
    );
    expect(requests(fetchMock, "PUT")).toHaveLength(1);
    expect(requests(fetchMock, "DELETE")).toHaveLength(1);
    expect(fetchMock.unexpected).toEqual([]);
  });
});
