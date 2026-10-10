import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PoolShareEditor } from "@/features/strategies/PoolShareEditor";
import { useStrategy } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";
import { useTokenStore } from "@/shared/auth/token-store";
import i18n from "@/shared/i18n";
import { jsonResponse } from "@/test/harness";
import { pressRangeKey } from "@/test/keyboard";

const ID = "11111111-1111-4111-8111-111111111111";

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: ID,
    name: "ETH Breakout",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    allocation_percent: "30",
    enabled: false,
    archived_at: null,
    allowed_pairs: ["ETHUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    ...overrides,
  };
}

interface Request {
  method: string;
  path: string;
  body: string | undefined;
}

interface Options {
  /** What a PATCH answers. By default: 200, the strategy with the share it was sent. */
  patch?: (sent: string) => Promise<Response> | Response;
}

/** The strategy as the server holds it: a PATCH that succeeds changes it, a test may also change it by hand. */
interface Server {
  strategy: Strategy;
  /** Set once the strategy has been deleted: a read answers 404. */
  gone?: boolean;
}

/** Every request the control makes, in order. */
function stub(server: Server, options: Options) {
  const requests: Request[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    requests.push({ method: init?.method ?? "GET", path, body: typeof init?.body === "string" ? init.body : undefined });
    if (init?.method === "PATCH") {
      const sent = String(init.body);
      if (options.patch !== undefined) return Promise.resolve(options.patch(sent));
      const { allocation_percent } = JSON.parse(sent) as { allocation_percent: string };
      server.strategy = { ...server.strategy, allocation_percent };
      return Promise.resolve(jsonResponse(server.strategy));
    }
    if (path === `/api/strategies/${ID}`) {
      return Promise.resolve(server.gone ? jsonResponse({ detail: "no such strategy" }, 404) : jsonResponse(server.strategy));
    }
    return Promise.resolve(jsonResponse({ detail: "not served by this test" }, 404));
  });
  vi.stubGlobal("fetch", fetchMock);
  return requests;
}

function newClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

/** The editor over a strategy handed in as a prop, which the test moves by hand with `rerender`. */
function setup(subject: Strategy, options: Options = {}) {
  const requests = stub({ strategy: subject }, options);
  const client = newClient();
  const ui = (current: Strategy) => (
    <QueryClientProvider client={client}>
      <PoolShareEditor strategy={current} />
    </QueryClientProvider>
  );
  const view = render(ui(subject));
  const patches = () => requests.filter((request) => request.method === "PATCH");
  return { requests, patches, rerender: (current: Strategy) => view.rerender(ui(current)), unmount: view.unmount };
}

/** The editor in the page's position: the strategy comes from `useStrategy`, as a save's answer and re-read move it. */
function Page() {
  const subject = useStrategy(ID);
  return subject.data === undefined ? <p>{subject.status}</p> : <PoolShareEditor strategy={subject.data} />;
}

function setupPage(subject: Strategy, options: Options = {}) {
  const server: Server = { strategy: subject };
  const requests = stub(server, options);
  const client = newClient();
  const ui = (
    <QueryClientProvider client={client}>
      <Page />
    </QueryClientProvider>
  );
  const view = render(ui);
  const patches = () => requests.filter((request) => request.method === "PATCH");
  const reads = () => requests.filter((request) => request.method === "GET" && request.path === `/api/strategies/${ID}`);
  /** Leaves the page and comes back to it: the cache stays, the control is a new one. */
  const leaveAndReturn = () => {
    view.unmount();
    render(ui);
  };
  return { server, requests, patches, reads, leaveAndReturn };
}

/** The visible label, in the language in force, so the same helpers serve both languages. */
const label = () => i18n.t("strategies.detail.share.label");
const field = () => screen.getByRole("textbox", { name: label() }) as HTMLInputElement;
const track = () => screen.getByRole("slider", { name: label() }) as HTMLInputElement;
const stop = (value: number) => screen.getByRole("button", { name: `Set the share to ${value}%` });
const saveButton = () => screen.getByRole("button", { name: "Save share" });
const type = (text: string) => fireEvent.change(field(), { target: { value: text } });
/** Lets any request a change started reach the fetch double: a mutation calls it a tick after the event. */
const settle = () => act(() => new Promise<void>((resolve) => setTimeout(resolve, 20)));
const moveHandle = (key: string) => {
  track().focus();
  pressRangeKey(key);
};

beforeEach(() => {
  useTokenStore.setState({ token: "a-token" });
});
afterEach(() => {
  vi.unstubAllGlobals();
  useTokenStore.setState({ token: null });
});

describe("PoolShareEditor, step 3: the value and Save", () => {
  it("a stored 33.5 shows 33.5 in the field and the handle at 34", () => {
    setup(strategy({ allocation_percent: "33.5" }));

    expect(field().value).toBe("33.5");
    expect(track().value).toBe("34");
    expect(track()).toHaveAttribute("aria-valuetext", "33.5% of the pool");
  });

  it("a stored 33.50 is shown in its plain form, 33.5, with Save disabled", () => {
    setup(strategy({ allocation_percent: "33.50" }));

    expect(field().value).toBe("33.5");
    expect(saveButton()).toBeDisabled();
  });

  it("a stored 0.5 shows 0.5 with the handle at the start of the track", () => {
    setup(strategy({ allocation_percent: "0.5" }));

    expect(field().value).toBe("0.5");
    expect(track().value).toBe("1");
  });

  it("moving the handle writes a whole number into the field", () => {
    setup(strategy({ allocation_percent: "33.5" }));

    moveHandle("ArrowRight");
    expect(field().value).toBe("35");
    expect(track().value).toBe("35");
  });

  it("one arrow down from a stored 33.5 gives 33", () => {
    setup(strategy({ allocation_percent: "33.5" }));

    moveHandle("ArrowLeft");
    expect(field().value).toBe("33");
  });

  it("a stop jumps to its value", () => {
    setup(strategy({ allocation_percent: "33.5" }));

    fireEvent.click(stop(75));

    expect(field().value).toBe("75");
    expect(track().value).toBe("75");
    expect(stop(75)).toHaveAttribute("aria-pressed", "true");
    expect(stop(25)).toHaveAttribute("aria-pressed", "false");
  });

  it("typing keeps the text as typed and the handle follows only a valid value", () => {
    setup(strategy({ allocation_percent: "33.5" }));

    type("62.5");
    expect(field().value).toBe("62.5");
    expect(track().value).toBe("63");

    type("62.5x");
    expect(field().value).toBe("62.5x");
    expect(track().value).toBe("63");

    type("");
    expect(field().value).toBe("");
    expect(track().value).toBe("63");
  });

  it("33,5 is sent as 33.5", async () => {
    const { patches } = setup(strategy());

    type("33,5");
    expect(field().value).toBe("33,5");
    fireEvent.click(saveButton());

    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0]?.body).toBe('{"allocation_percent":"33.5"}');
  });

  it.each([
    ["0", "0"],
    ["100.5", "100.5"],
    ["an empty field", ""],
    ["abc", "abc"],
  ])("%s leaves Save disabled", async (_name, text) => {
    const { patches } = setup(strategy());

    type(text);

    expect(saveButton()).toBeDisabled();
    fireEvent.click(saveButton());
    await settle();
    expect(patches()).toHaveLength(0);
  });

  it("0.5 is valid and can be saved", async () => {
    const { patches } = setup(strategy());

    type("0.5");

    expect(saveButton()).toBeEnabled();
    expect(track().value).toBe("1");
    fireEvent.click(saveButton());
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0]?.body).toBe('{"allocation_percent":"0.5"}');
  });

  it("the stored value typed back leaves Save disabled", () => {
    setup(strategy({ allocation_percent: "33.50" }));

    type("40");
    expect(saveButton()).toBeEnabled();
    type("33.5");

    expect(saveButton()).toBeDisabled();
  });

  it("Save is enabled only for a valid value that differs from the stored one on an unarchived strategy", () => {
    setup(strategy());
    expect(saveButton()).toBeDisabled();

    type("40");
    expect(saveButton()).toBeEnabled();

    type("0");
    expect(saveButton()).toBeDisabled();
  });

  it("Save stays disabled on an archived strategy", () => {
    setup(strategy({ archived_at: "2026-10-01T00:00:00Z" }));

    expect(saveButton()).toBeDisabled();
    expect(field()).toBeDisabled();
  });

  it("Save stays disabled when a change was made and the strategy is then archived", () => {
    const { rerender } = setup(strategy());

    type("40");
    expect(saveButton()).toBeEnabled();
    rerender(strategy({ archived_at: "2026-10-01T00:00:00Z" }));

    expect(field().value).toBe("40");
    expect(saveButton()).toBeDisabled();
    fireEvent.click(saveButton());
    expect(field()).toBeDisabled();
  });

  it("no request is made before Save, whatever is moved, activated or typed", async () => {
    const { requests } = setup(strategy());

    moveHandle("End");
    fireEvent.click(stop(25));
    type("12.5");
    type("abc");
    await settle();

    expect(requests).toEqual([]);
  });

  it("leaving the page after a change sends nothing", async () => {
    const { requests, unmount } = setup(strategy());

    type("40");
    unmount();
    await settle();

    expect(requests).toEqual([]);
  });

  it("the request body is exactly the share as a string", async () => {
    const { patches } = setup(strategy());

    type("33.5");
    fireEvent.click(saveButton());

    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0]).toEqual({
      method: "PATCH",
      path: `/api/strategies/${ID}`,
      body: '{"allocation_percent":"33.5"}',
    });
  });

  it("a draft made on a stored value is dropped when the stored value moves", () => {
    const { rerender } = setup(strategy({ allocation_percent: "30" }));

    type("40");
    expect(field().value).toBe("40");
    rerender(strategy({ allocation_percent: "55" }));

    expect(field().value).toBe("55");
    expect(track().value).toBe("55");
    expect(saveButton()).toBeDisabled();
  });

  it("the control makes no request but the share preview and the save", async () => {
    const { requests } = setup(strategy());

    type("40");
    fireEvent.click(saveButton());
    await waitFor(() => expect(requests.some((request) => request.method === "PATCH")).toBe(true));

    const allowed = [`/api/strategies/${ID}`, `/api/strategies/${ID}/share-preview`];
    for (const request of requests) {
      expect(allowed).toContain(request.path.split("?")[0]);
      expect(request.path).not.toMatch(/pool|available-pairs|webhook|secret/);
    }
  });

  it.each([
    ["abc", "Enter a number, for example 25 or 33.5."],
    ["", "Enter a number, for example 25 or 33.5."],
    ["0", "The share must be above 0 and at most 100."],
    ["100.5", "The share must be above 0 and at most 100."],
    ["33.3333333333333333333", "A share has at most 18 decimal places."],
  ])("the refusal of %j reads %j, tied to the field and not an alert", (text, refusal) => {
    setup(strategy());

    type(text);

    expect(screen.queryByText(refusal)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(field()).toHaveAttribute("aria-invalid", "true");
    expect(field()).toHaveAccessibleDescription(refusal);
  });

  it("a valid value shows no refusal text", () => {
    setup(strategy());

    type("33.5");

    expect(field()).toHaveAttribute("aria-invalid", "false");
    expect(field()).toHaveAccessibleDescription("");
  });

  it("a 19-decimal share sends no request and Save stays disabled, a 18-decimal one can be saved", async () => {
    const { requests, patches } = setup(strategy());

    type("0.1234567890123456789");
    expect(saveButton()).toBeDisabled();
    fireEvent.click(saveButton());
    await settle();
    expect(requests).toEqual([]);

    type("0.123456789012345678");
    expect(saveButton()).toBeEnabled();
    fireEvent.click(saveButton());
    await waitFor(() => expect(patches()).toHaveLength(1));
  });

  it("the refusal texts are in Spanish when the language is", async () => {
    await i18n.changeLanguage("es");
    try {
      setup(strategy());

      type("33.3333333333333333333");

      expect(screen.getByText("El porcentaje tiene como máximo 18 decimales.")).toBeInTheDocument();
      type("abc");
      expect(screen.getByText("Escriba un número, por ejemplo 25 o 33,5.")).toBeInTheDocument();
      type("0");
      expect(screen.getByText("El porcentaje debe ser mayor que 0 y como máximo 100.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Guardar porcentaje" })).toBeDisabled();
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });
});

const SAVE_FAILED = "The share was not saved. Try again.";
const OUT_OF_RANGE = "The share must be above 0 and at most 100.";
const ARCHIVED = "This strategy is archived and can no longer be changed.";
const GONE = "This strategy no longer exists.";
const UNREADABLE = "The stored share could not be read, so it cannot be edited here.";

const refuse = (status: number, detail: unknown) => () => jsonResponse({ detail }, status);

/** The one alert line, once it has appeared. Presence is asserted, so a missing line fails on its assertion. */
async function alertLine(): Promise<HTMLElement> {
  await waitFor(() => expect(screen.queryByRole("alert")).toBeInTheDocument());
  return screen.getByRole("alert");
}

describe("PoolShareEditor, step 3b: the states and the refusals", () => {
  it("while saving, Save reads Saving... and the track, the stops and the field are disabled", async () => {
    setup(strategy(), { patch: () => new Promise<Response>(() => undefined) });

    type("40");
    fireEvent.click(saveButton());

    const saving = await screen.findByRole("button", { name: "Saving…" });
    expect(saving).toBeDisabled();
    expect(field()).toBeDisabled();
    expect(track()).toBeDisabled();
    for (const value of [25, 50, 75, 100]) expect(stop(value)).toBeDisabled();
  });

  it("a 422 shows the out-of-range text as an alert and keeps the draft", async () => {
    setup(strategy(), { patch: refuse(422, [{ msg: "refused" }]) });

    type("40");
    fireEvent.click(saveButton());

    expect(await alertLine()).toHaveTextContent(OUT_OF_RANGE);
    expect(field().value).toBe("40");
    expect(saveButton()).toBeEnabled();
  });

  it("a 409 STRATEGY_ARCHIVED shows the archived text, the page re-reads the strategy and the control turns read-only", async () => {
    const page = setupPage(strategy(), {
      patch: () => {
        page.server.strategy = { ...page.server.strategy, archived_at: "2026-10-09T10:00:00Z" };
        return jsonResponse({ detail: { error: "STRATEGY_ARCHIVED", message: "archived" } }, 409);
      },
    });
    await screen.findByRole("textbox");

    type("40");
    fireEvent.click(saveButton());

    expect(await alertLine()).toHaveTextContent(ARCHIVED);
    await waitFor(() => expect(page.reads().length).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(field()).toBeDisabled());
    expect(track()).toBeDisabled();
    expect(saveButton()).toBeDisabled();
    for (const value of [25, 50, 75, 100]) expect(stop(value)).toBeDisabled();
  });

  it("a 404 shows 'This strategy no longer exists.' and the strategy is read again for the page to show its not-found state", async () => {
    const page = setupPage(strategy(), {
      patch: () => {
        page.server.gone = true;
        return jsonResponse({ detail: "no such strategy" }, 404);
      },
    });
    await screen.findByRole("textbox");

    type("40");
    fireEvent.click(saveButton());

    expect(await alertLine()).toHaveTextContent(GONE);
    await waitFor(() => expect(page.reads().length).toBeGreaterThanOrEqual(2));
  });

  it.each([
    ["a network failure", () => Promise.reject(new TypeError("Failed to fetch"))],
    ["a 500", refuse(500, "boom")],
    ["a 503", refuse(503, "unavailable")],
    ["a 200 whose body is not a strategy", () => jsonResponse({ id: 7 })],
  ])("%s shows the failure text and keeps the draft", async (_name, patch) => {
    setup(strategy(), { patch });

    type("33.5");
    fireEvent.click(saveButton());

    expect(await alertLine()).toHaveTextContent(SAVE_FAILED);
    expect(field().value).toBe("33.5");
    expect(track().value).toBe("34");
    expect(saveButton()).toBeEnabled();
  });

  it("an archived strategy's track, stops, field and Save are disabled", () => {
    setup(strategy({ archived_at: "2026-10-01T00:00:00Z", allocation_percent: "30" }));

    expect(field()).toBeDisabled();
    expect(track()).toBeDisabled();
    expect(saveButton()).toBeDisabled();
    for (const value of [25, 50, 75, 100]) expect(stop(value)).toBeDisabled();
    expect(field().value).toBe("30");
  });

  it.each(["1E-7", "", "1E+1", "+5", "abc"])("a stored value %j that cannot be read shows its text and no control", (stored) => {
    setup(strategy({ allocation_percent: stored }));

    expect(screen.queryByText(UNREADABLE)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("slider")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save share" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Set the share/ })).toBeNull();
  });

  it("each refusal is a role=alert line, one at a time, and none shows before a save", async () => {
    setup(strategy(), { patch: refuse(500, "boom") });
    expect(screen.queryByRole("alert")).toBeNull();

    type("40");
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(saveButton());

    await alertLine();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("the unreadable text is in Spanish when the language is", async () => {
    await i18n.changeLanguage("es");
    try {
      setup(strategy({ allocation_percent: "1E-7" }));
      expect(
        screen.queryByText("No se pudo leer el porcentaje guardado, por lo que no se puede editar aquí."),
      ).toBeInTheDocument();
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });

  it("the failure text is in Spanish when the language is", async () => {
    await i18n.changeLanguage("es");
    try {
      setup(strategy(), { patch: refuse(500, "boom") });
      type("40");
      fireEvent.click(screen.getByRole("button", { name: "Guardar porcentaje" }));
      expect(await alertLine()).toHaveTextContent("El porcentaje no se guardó. Inténtelo de nuevo.");
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });

  it("the archived text is in Spanish when the language is", async () => {
    await i18n.changeLanguage("es");
    try {
      setup(strategy(), { patch: refuse(409, { error: "STRATEGY_ARCHIVED", message: "archived" }) });
      type("40");
      fireEvent.click(screen.getByRole("button", { name: "Guardar porcentaje" }));
      expect(await alertLine()).toHaveTextContent("Esta estrategia está archivada y ya no se puede modificar.");
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });
});

/** The live region beside Save, which is where "Saved" is written. */
function savedRegion(): HTMLElement {
  const region = saveButton().parentElement?.querySelector<HTMLElement>('[role="status"]');
  if (region === null || region === undefined) throw new Error("no live region beside Save");
  return region;
}

/** Saves 40 on a page and waits for "Saved". */
async function saveFortyOnAPage(options: Options = {}) {
  const page = setupPage(strategy(), options);
  await screen.findByRole("textbox");
  type("40");
  fireEvent.click(saveButton());
  await waitFor(() => expect(savedRegion()).toHaveTextContent("Saved"));
  return page;
}

describe("PoolShareEditor, 'Saved' for the share", () => {
  it("Saved shows when the PATCH answers 200 with a strategy", async () => {
    await saveFortyOnAPage();

    expect(field().value).toBe("40");
    expect(saveButton()).toBeDisabled();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("the live region exists before the save, empty, and is the same element after it", async () => {
    setupPage(strategy());
    await screen.findByRole("textbox");
    const before = savedRegion();

    expect(before).toBeEmptyDOMElement();
    expect(before).toHaveAttribute("aria-live", "polite");
    type("40");
    fireEvent.click(saveButton());
    await waitFor(() => expect(savedRegion()).toHaveTextContent("Saved"));
    expect(savedRegion()).toBe(before);
  });

  it("Saved is still there ten minutes later", async () => {
    await saveFortyOnAPage();

    vi.useFakeTimers();
    try {
      await act(async () => {
        vi.advanceTimersByTime(600_000);
      });
      expect(savedRegion()).toHaveTextContent("Saved");
    } finally {
      vi.useRealTimers();
    }
  });

  it.each([
    ["the handle moves", () => moveHandle("ArrowRight")],
    ["a stop is activated", () => fireEvent.click(stop(75))],
    ["a key is typed in the field", () => type("41")],
  ])("Saved goes when %s", async (_name, change) => {
    await saveFortyOnAPage();

    change();

    expect(savedRegion()).toBeEmptyDOMElement();
  });

  it.each([
    ["a 422", refuse(422, [{ msg: "refused" }])],
    ["a 409", refuse(409, { error: "STRATEGY_ARCHIVED", message: "archived" })],
    ["a 404", refuse(404, "no such strategy")],
    ["a 500", refuse(500, "boom")],
    ["a network failure", () => Promise.reject(new TypeError("Failed to fetch"))],
    ["a 200 whose body is not a strategy", () => jsonResponse({ id: 7 })],
  ])("no Saved after %s", async (_name, patch) => {
    setup(strategy(), { patch });

    type("40");
    fireEvent.click(saveButton());

    await alertLine();
    expect(savedRegion()).toBeEmptyDOMElement();
  });

  it("a new save clears Saved before it is sent", async () => {
    let calls = 0;
    const { requests } = setup(strategy(), {
      patch: (sent) => {
        calls += 1;
        if (calls > 1) return new Promise<Response>(() => undefined);
        const { allocation_percent } = JSON.parse(sent) as { allocation_percent: string };
        return jsonResponse({ ...strategy(), allocation_percent });
      },
    });
    type("40");
    fireEvent.click(saveButton());
    await waitFor(() => expect(savedRegion()).toHaveTextContent("Saved"));

    // The stored value did not move in this test, so Save is still enabled for the same draft.
    fireEvent.click(saveButton());

    expect(savedRegion()).toBeEmptyDOMElement();
    await settle();
    expect(requests.filter((request) => request.method === "PATCH")).toHaveLength(2);
  });

  it("a refusal and Saved are never on screen together", async () => {
    let calls = 0;
    setup(strategy(), {
      patch: (sent) => {
        calls += 1;
        if (calls > 1) return jsonResponse({ detail: "boom" }, 500);
        const { allocation_percent } = JSON.parse(sent) as { allocation_percent: string };
        return jsonResponse({ ...strategy(), allocation_percent });
      },
    });
    type("40");
    fireEvent.click(saveButton());
    await waitFor(() => expect(savedRegion()).toHaveTextContent("Saved"));
    expect(screen.queryByRole("alert")).toBeNull();

    fireEvent.click(saveButton());

    expect(await alertLine()).toHaveTextContent("The share was not saved. Try again.");
    expect(savedRegion()).toBeEmptyDOMElement();
  });

  it("Saved is neutral ink, not gain", async () => {
    await saveFortyOnAPage();

    expect(savedRegion()).toHaveClass("text-ink-2");
    expect(savedRegion().className).not.toMatch(/gain/);
  });

  it("Saved is gone when the page is left and the control is shown again", async () => {
    const page = await saveFortyOnAPage();

    page.leaveAndReturn();

    await waitFor(() => expect(field().value).toBe("40"));
    expect(savedRegion()).toBeEmptyDOMElement();
  });

  it("Saved reads Guardado in Spanish", async () => {
    await i18n.changeLanguage("es");
    try {
      setupPage(strategy());
      await screen.findByRole("textbox");
      type("40");
      fireEvent.click(screen.getByRole("button", { name: "Guardar porcentaje" }));
      await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Guardado"));
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });
});
