import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PoolShareEditor } from "@/features/strategies/PoolShareEditor";
import { useStrategy } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";
import { useTokenStore } from "@/shared/auth/token-store";
import i18n from "@/shared/i18n";
import { jsonResponse, pool } from "@/test/harness";
import { pressRangeKey, pressTab } from "@/test/keyboard";

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
  /** What a GET of the share preview answers, given the `share` asked (null for the stored share). Default: a 500. */
  preview?: (share: string | null) => Promise<Response> | Response;
  /** When set, `GET /api/pools` answers one pool holding this total, a balance the control must never multiply. */
  pools?: string;
}

/** A served preview: a pool of 1000 USDT, so step N asks for 10 x N, and a minimum order of 5. */
interface PreviewSpec {
  total?: string;
  minimum?: string;
  currency?: string;
  stale?: boolean;
  observedAt?: string;
  /** The exact amount for the stored (or asked) share, as served. Default: absent, the stored share is whole. */
  exact?: { share: string; amount: string; below?: boolean };
  /** A pool nothing has synced: no balance, no exact, no steps. */
  noBalance?: boolean;
  /** A step list of this length instead of 100. */
  stepCount?: number;
  /** What one point of share asks for, so step N asks for `unit` x N. Default 10, a pool of 1000. */
  unit?: number;
}

function previewBody(spec: PreviewSpec = {}) {
  const minimum = spec.minimum ?? "5.000000000000000000";
  const steps = Array.from({ length: spec.stepCount ?? 100 }, (_unused, index) => {
    const amount = (spec.unit ?? 10) * (index + 1);
    return { share: index + 1, amount: amount.toFixed(18), below_pool_minimum: amount < Number(minimum) };
  });
  const base = {
    strategy_id: ID,
    pool: { exchange: "bybit", venue: "usdt-m", settlement_currency: spec.currency ?? "USDT" },
    currency: spec.currency ?? "USDT",
    pool_minimum: minimum,
  };
  if (spec.noBalance === true) return { ...base, balance: null, exact: null, steps: [] };
  return {
    ...base,
    balance: {
      total: spec.total ?? "1000.000000000000000000",
      observed_at: spec.observedAt ?? "2026-10-09T14:03:12Z",
      stale: spec.stale ?? false,
    },
    exact:
      spec.exact === undefined
        ? { share: "30", amount: "300.000000000000000000", below_pool_minimum: false }
        : { share: spec.exact.share, amount: spec.exact.amount, below_pool_minimum: spec.exact.below ?? false },
    steps,
  };
}

const served = (spec: PreviewSpec = {}) => () => jsonResponse(previewBody(spec));

/** The strategy as the server holds it: a PATCH that succeeds changes it, a test may also change it by hand. */
interface Server {
  strategy: Strategy;
  /** Set once the strategy has been deleted: a read answers 404. */
  gone?: boolean;
}

/** Every request the control makes, in order; the reads of the share preview are kept apart, in `previews`. */
function stub(server: Server, options: Options) {
  const requests: Request[] = [];
  const previews: Array<string | null> = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.startsWith(`/api/strategies/${ID}/share-preview`)) {
      const share = new URL(path, "http://panel.test").searchParams.get("share");
      previews.push(share);
      return Promise.resolve(options.preview?.(share) ?? jsonResponse({ detail: "no preview in this test" }, 500));
    }
    if (path === "/api/pools" && options.pools !== undefined) {
      const balance = { total: options.pools, available: options.pools, observed_at: "2026-10-09T14:00:00Z", stale: false };
      return Promise.resolve(jsonResponse([pool("bybit", "usdt-m", "USDT", balance)]));
    }
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
  return { requests, previews };
}

function newClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

/** The editor over a strategy handed in as a prop, which the test moves by hand with `rerender`. */
function setup(subject: Strategy, options: Options = {}) {
  const { requests, previews } = stub({ strategy: subject }, options);
  const client = newClient();
  const ui = (current: Strategy) => (
    <QueryClientProvider client={client}>
      <PoolShareEditor strategy={current} />
    </QueryClientProvider>
  );
  const view = render(ui(subject));
  const patches = () => requests.filter((request) => request.method === "PATCH");
  return {
    client,
    requests,
    previews,
    patches,
    rerender: (current: Strategy) => view.rerender(ui(current)),
    unmount: view.unmount,
  };
}

/** The editor in the page's position: the strategy comes from `useStrategy`, as a save's answer and re-read move it. */
function Page() {
  const subject = useStrategy(ID);
  return subject.data === undefined ? <p>{subject.status}</p> : <PoolShareEditor strategy={subject.data} />;
}

function setupPage(subject: Strategy, options: Options = {}) {
  const server: Server = { strategy: subject };
  const { requests, previews } = stub(server, options);
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
  return { server, requests, previews, patches, reads, leaveAndReturn };
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

/** The live region beside Save, which is where "Saved" is announced. */
function savedRegion(): HTMLElement {
  // The button reads "Saving…" while a save is in flight and "Saved" after it, so it is found by any of its names.
  const button = screen.getByRole("button", { name: /^(Save share|Saving…|Saved)$/ });
  const region = button.parentElement?.querySelector<HTMLElement>('[role="status"]');
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
    expect(screen.getByRole("button", { name: "Saved" })).toBeDisabled();
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
    // The fake clock is installed before the save, so a timer the control starts is a fake one too.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      await saveFortyOnAPage();

      await act(async () => {
        vi.advanceTimersByTime(600_000);
      });
      expect(savedRegion()).toHaveTextContent("Saved");
      expect(screen.queryByRole("button", { name: "Saved" })).toBeInTheDocument();
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
    // The button's own text goes back to Save, and it can save the new value.
    expect(screen.queryByRole("button", { name: "Saved" })).toBeNull();
    expect(saveButton()).toBeEnabled();
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
    expect(screen.queryByRole("button", { name: "Saved" })).toBeNull();
    expect(saveButton()).toBeEnabled();
  });

  // A button that reads Saved is disabled, so the same draft cannot be sent twice from it. This replaces
  // "a new save clears Saved before it is sent", which clicked the button while it read Saved.
  it("a button that reads Saved is disabled and sends nothing when pressed", async () => {
    // Not on a page: the stored value does not move here, so only the Saved text disables the button.
    const { requests } = setup(strategy());
    type("40");
    fireEvent.click(saveButton());
    await waitFor(() => expect(savedRegion()).toHaveTextContent("Saved"));

    const saved = screen.getByRole("button", { name: "Saved" });
    fireEvent.click(saved);
    await settle();

    expect(saved).toBeDisabled();
    expect(requests.filter((request) => request.method === "PATCH")).toHaveLength(1);
    expect(savedRegion()).toHaveTextContent("Saved");
  });

  it("a new save, after a change, reads Saving… and Saved is gone while it is in flight", async () => {
    let calls = 0;
    setup(strategy(), {
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

    type("41");
    fireEvent.click(saveButton());

    expect(await screen.findByRole("button", { name: "Saving…" })).toBeDisabled();
    expect(savedRegion()).toBeEmptyDOMElement();
    expect(screen.queryByRole("button", { name: "Saved" })).toBeNull();
  });

  // The refusal arrives for a save sent after a change; the earlier "Saved" is gone by then, as the change
  // itself ends it. This replaces a test that pressed the button while it still read Saved.
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

    type("41");
    fireEvent.click(saveButton());

    expect(await alertLine()).toHaveTextContent("The share was not saved. Try again.");
    expect(savedRegion()).toBeEmptyDOMElement();
    expect(screen.queryByRole("button", { name: "Saved" })).toBeNull();
    expect(saveButton()).toBeEnabled();
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

const amountLine = (amount: string, currency = "USDT") => `Asks for about ${amount} ${currency} per operation`;
/** Waits for a text to be on screen; presence is asserted so a missing text fails on its assertion. */
const expectText = (text: string) => waitFor(() => expect(screen.queryByText(text)).toBeInTheDocument());

describe("PoolShareEditor, the amount under the track", () => {
  it("a known amount reads 'Asks for about 335.00 USDT per operation' from the served exact", async () => {
    setup(strategy({ allocation_percent: "33.5" }), {
      preview: served({ exact: { share: "33.5", amount: "335.000000000000000000" } }),
    });

    await expectText(amountLine("335.00"));
  });

  it("every whole value shows the amount of its own step", async () => {
    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));

    fireEvent.click(stop(25));
    await expectText(amountLine("250.00"));
    fireEvent.click(stop(100));
    await expectText(amountLine("1,000.00"));
    moveHandle("ArrowLeft");
    await expectText(amountLine("990.00"));
    type("34");
    await expectText(amountLine("340.00"));
    type("1");
    await expectText(amountLine("10.00"));
    fireEvent.click(stop(75));
    await expectText(amountLine("750.00"));
  });

  it("dragging the handle and activating a stop send no request and the figure follows at once", async () => {
    const { previews } = setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));

    moveHandle("Home");
    expect(screen.queryByText(amountLine("10.00"))).toBeInTheDocument();
    moveHandle("End");
    expect(screen.queryByText(amountLine("1,000.00"))).toBeInTheDocument();
    fireEvent.click(stop(50));
    expect(screen.queryByText(amountLine("500.00"))).toBeInTheDocument();
    await settle();

    expect(previews).toEqual([null]);
  });

  it("the stored share with decimals shows the first read's exact and sends no second request", async () => {
    const { previews } = setup(strategy({ allocation_percent: "33.50" }), {
      preview: served({ exact: { share: "33.5", amount: "335.000000000000000000" } }),
    });

    await expectText(amountLine("335.00"));
    await settle();

    expect(previews).toEqual([null]);
  });

  it("the amount is cut down as text to the currency's decimals and never rounded up", async () => {
    setup(strategy({ allocation_percent: "0.4996" }), {
      preview: served({ exact: { share: "0.4996", amount: "4.996000000000000000" } }),
    });

    await expectText(amountLine("4.99"));
    expect(screen.queryByText(amountLine("5.00"))).toBeNull();
  });

  it("a coin-margined pool uses its own decimals", async () => {
    setup(strategy({ allocation_percent: "12.5", settlement_currency: "BTC" }), {
      preview: served({ currency: "BTC", exact: { share: "12.5", amount: "0.123456789999999999" } }),
    });

    await expectText(amountLine("0.12345678", "BTC"));
  });

  it("a stale balance shows the same line and when it was last read", async () => {
    setup(strategy(), { preview: served({ stale: true, observedAt: "2026-10-09T14:03:12Z" }) });

    await expectText(amountLine("300.00"));
    await expectText("The pool's balance was last read at 14:03 UTC and may be out of date.");
  });

  it("a balance that is not stale shows no stale line", async () => {
    setup(strategy(), { preview: served() });

    await expectText(amountLine("300.00"));
    expect(screen.queryByText(/may be out of date/)).toBeNull();
  });

  it("no balance shows its sentence and no figure, never a zero, and the control stays usable", async () => {
    const { patches } = setup(strategy(), { preview: served({ noBalance: true }) });

    await expectText("The pool's balance has not been read yet, so the amount cannot be shown.");
    expect(screen.queryByText(/Asks for about/)).toBeNull();
    expect(field()).toBeEnabled();
    fireEvent.click(stop(50));
    expect(saveButton()).toBeEnabled();
    fireEvent.click(saveButton());
    await waitFor(() => expect(patches()).toHaveLength(1));
  });

  it("loading shows 'Calculating the amount…' and no figure", async () => {
    setup(strategy(), { preview: () => new Promise<Response>(() => undefined) });

    await expectText("Calculating the amount…");
    expect(screen.queryByText(/Asks for about/)).toBeNull();
    expect(screen.queryByText("—")).toBeNull();
  });

  it("a failed read shows 'The amount could not be loaded.' and the track, the stops, the field and Save stay usable", async () => {
    const { patches } = setup(strategy(), { preview: () => jsonResponse({ detail: "boom" }, 500) });

    await expectText("The amount could not be loaded.");
    expect(screen.queryByText(/Asks for about/)).toBeNull();
    expect(field()).toBeEnabled();
    expect(track()).toBeEnabled();
    for (const value of [25, 50, 75, 100]) expect(stop(value)).toBeEnabled();
    fireEvent.click(stop(50));
    expect(saveButton()).toBeEnabled();
    fireEvent.click(saveButton());
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0]?.body).toBe('{"allocation_percent":"50"}');
  });

  it("a body that fails the panel's check is an error and no figure from it shows", async () => {
    setup(strategy(), { preview: served({ stepCount: 99 }) });

    await expectText("The amount could not be loaded.");
    expect(screen.queryByText(/Asks for about/)).toBeNull();
  });

  it("no valid value shows an em dash and no request is made for it", async () => {
    const { previews } = setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));

    type("abc");

    expect(screen.queryByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/Asks for about/)).toBeNull();
    await settle();
    expect(previews).toEqual([null]);
  });

  it("the figure is the served string, never the pool's balance multiplied", async () => {
    setup(strategy({ allocation_percent: "33.5" }), {
      preview: served({ exact: { share: "33.5", amount: "335.000000000000000000" } }),
      pools: "900.000000000000000000",
    });

    await expectText(amountLine("335.00"));
    // 900 x 33.5 / 100 would read 301.50.
    expect(screen.queryByText(amountLine("301.50"))).toBeNull();
  });

  it("two pools are never summed or converted", async () => {
    const other = "22222222-2222-4222-8222-222222222222";
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const path = String(input);
        if (path.includes(other)) {
          return Promise.resolve(
            jsonResponse(previewBody({ currency: "BTC", exact: { share: "12.5", amount: "0.123456789999999999" } })),
          );
        }
        return Promise.resolve(jsonResponse(previewBody({ exact: { share: "33.5", amount: "335.000000000000000000" } })));
      }),
    );
    render(
      <QueryClientProvider client={newClient()}>
        <PoolShareEditor strategy={strategy({ allocation_percent: "33.5" })} />
        <PoolShareEditor strategy={strategy({ id: other, allocation_percent: "12.5", settlement_currency: "BTC" })} />
      </QueryClientProvider>,
    );

    await expectText(amountLine("335.00"));
    await expectText(amountLine("0.12345678", "BTC"));
    expect(screen.queryByText(/335\.12|335\.0012|USDT.*BTC.*per/)).toBeNull();
  });

  it("the amount reads in Spanish when the language is", async () => {
    await i18n.changeLanguage("es");
    try {
      setup(strategy({ allocation_percent: "33.5" }), {
        preview: served({ exact: { share: "33.5", amount: "1234.569999999999999999" } }),
      });

      await expectText("Pide alrededor de 1234,56 USDT por operación");
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });
});

const LOADING = "Calculating the amount…";
const FAILED = "The amount could not be loaded.";

/** Moves the fake clock and lets the work it starts finish: timers, promises and React's updates. */
const tick = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

/** A preview whose answer for an asked share is held until the test lets it go. */
function heldPreview(spec: PreviewSpec = {}) {
  const held = new Map<string, (response: Response) => void>();
  const preview = (share: string | null) =>
    share === null
      ? jsonResponse(previewBody(spec))
      : new Promise<Response>((resolve) => {
          held.set(share, resolve);
        });
  const answer = (share: string, amount: string, asked: string = share, below = false) =>
    held.get(share)?.(jsonResponse(previewBody({ ...spec, exact: { share: asked, amount, below } })));
  return { preview, answer, held };
}

describe("PoolShareEditor, the amount of a typed decimal", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  /** Mounts the editor on a stored 30 and waits, on the real clock, for the first read; then fakes the clock. */
  async function mounted(options: Options) {
    const view = setup(strategy(), options);
    await expectText(amountLine("300.00"));
    vi.useFakeTimers();
    return view;
  }

  it("a typed 12.34 shows no figure, only the loading mark, until its answer, and then that answer's", async () => {
    const { preview, answer } = heldPreview();
    const { previews } = await mounted({ preview });

    type("12.34");
    expect(screen.queryByText(LOADING)).toBeInTheDocument();
    expect(screen.queryByText(/Asks for about/)).toBeNull();
    expect(previews).toEqual([null]);
    await tick(299);
    expect(previews).toEqual([null]);
    expect(screen.queryByText(/Asks for about/)).toBeNull();
    await tick(1);
    expect(previews).toEqual([null, "12.34"]);
    expect(screen.queryByText(LOADING)).toBeInTheDocument();
    expect(screen.queryByText(/Asks for about/)).toBeNull();

    answer("12.34", "123.400000000000000000");
    await tick(0);

    expect(screen.queryByText(amountLine("123.40"))).toBeInTheDocument();
    expect(screen.queryByText(LOADING)).toBeNull();
  });

  it("two typed values in quick succession send one request, for the last, 300 ms after the last keystroke", async () => {
    const { preview, answer } = heldPreview();
    const { previews } = await mounted({ preview });

    type("12.3");
    await tick(200);
    type("12.34");
    await tick(299);
    expect(previews).toEqual([null]);
    await tick(1);

    expect(previews).toEqual([null, "12.34"]);
    answer("12.34", "123.400000000000000000");
    await tick(0);
    expect(screen.queryByText(amountLine("123.40"))).toBeInTheDocument();
  });

  it("an answer whose exact.share is not the value asked is refused", async () => {
    const { preview, answer } = heldPreview();
    await mounted({ preview });

    type("12.34");
    await tick(300);
    answer("12.34", "123.500000000000000000", "12.35");
    await tick(0);

    expect(screen.queryByText(FAILED)).toBeInTheDocument();
    expect(screen.queryByText(/Asks for about/)).toBeNull();
  });

  it("an answer is compared in plain form: 12.50 for 12.5 is the value asked", async () => {
    const { preview, answer } = heldPreview();
    await mounted({ preview });

    type("12.5");
    await tick(300);
    answer("12.5", "125.000000000000000000", "12.50");
    await tick(0);

    expect(screen.queryByText(amountLine("125.00"))).toBeInTheDocument();
  });

  it("an answer for a value the field no longer holds is not used", async () => {
    const { preview, answer } = heldPreview();
    const { previews } = await mounted({ preview });

    type("12.34");
    await tick(300);
    type("12.35");
    answer("12.34", "123.400000000000000000");
    await tick(0);

    expect(screen.queryByText(amountLine("123.40"))).toBeNull();
    expect(screen.queryByText(LOADING)).toBeInTheDocument();
    await tick(300);
    expect(previews).toEqual([null, "12.34", "12.35"]);
    answer("12.35", "123.500000000000000000");
    await tick(0);
    expect(screen.queryByText(amountLine("123.50"))).toBeInTheDocument();
  });

  it("a value below 1 asks once at rest and reads its own amount", async () => {
    const { preview, answer } = heldPreview();
    const { previews } = await mounted({ preview });

    type("0.5");
    expect(previews).toEqual([null]);
    await tick(300);
    expect(previews).toEqual([null, "0.5"]);
    answer("0.5", "5.000000000000000000");
    await tick(0);

    expect(screen.queryByText(amountLine("5.00"))).toBeInTheDocument();
    await tick(250);
    expect(previews).toEqual([null, "0.5"]);
  });

  it("a text that is not a valid value sends no request and shows the em dash", async () => {
    const { preview } = heldPreview();
    const { previews } = await mounted({ preview });

    type("12.");
    type("abc");
    await tick(1000);

    expect(previews).toEqual([null]);
    expect(screen.queryByText("—")).toBeInTheDocument();
  });

  it("a value past 18 decimal places sends no preview request either", async () => {
    const { preview } = heldPreview();
    const { previews } = await mounted({ preview });

    type("12.3456789012345678901");
    await tick(1000);

    expect(previews).toEqual([null]);
  });

  it.each([
    ["12,5", "12.5"],
    ["0033.50", "33.5"],
    ["100.0", null],
  ])("the request for a typed %s carries ?share= with the canonical text %s", async (typed, asked) => {
    const { preview } = heldPreview();
    const { previews } = await mounted({ preview });

    type(typed);
    await tick(300);

    expect(previews).toEqual(asked === null ? [null] : [null, asked]);
  });

  it("a whole value, a stop and the stored share ask for nothing at all", async () => {
    const { preview } = heldPreview();
    const { previews } = await mounted({ preview });

    type("34");
    fireEvent.click(stop(75));
    type("30");
    type("1");
    type("100");
    await tick(1000);

    expect(previews).toEqual([null]);
  });
});

const WARNING =
  "At this balance the share asks for less than the pool's minimum order, 5.00 USDT. Openings would be skipped until the share or the balance is larger.";

/** A pool of 300 USDT: step N asks for 3 x N, so step 1 asks for 3 and step 2 for 6, against a minimum of 5. */
const SMALL_POOL: PreviewSpec = { unit: 3, minimum: "5.000000000000000000" };

describe("PoolShareEditor, the warning on the pool's minimum", () => {
  it("a share that asks for less than the pool's minimum order shows the warning with the minimum, cut down as text", async () => {
    setup(strategy({ allocation_percent: "30" }), { preview: served({ ...SMALL_POOL, minimum: "5.999999999999999999" }) });
    await expectText(amountLine("90.00"));

    fireEvent.click(stop(25));
    expect(screen.queryByText(/less than the pool's minimum order/)).toBeNull();
    type("1");

    expect(
      screen.queryByText(
        "At this balance the share asks for less than the pool's minimum order, 5.99 USDT. Openings would be skipped until the share or the balance is larger.",
      ),
    ).toBeInTheDocument();
  });

  it("it is a role=status line in the loss colour, not an alert and never amber", async () => {
    setup(strategy({ allocation_percent: "1" }), { preview: served(SMALL_POOL) });

    await expectText(WARNING);

    const line = screen.getByText(WARNING);
    expect(line).toHaveAttribute("role", "status");
    expect(line).toHaveClass("text-loss");
    expect(line.className).not.toMatch(/decision/);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("it shows for a stored share under the minimum with no change made", async () => {
    setup(strategy({ allocation_percent: "1" }), { preview: served(SMALL_POOL) });

    await expectText(amountLine("3.00"));
    expect(screen.queryByText(WARNING)).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
  });

  it("the warning follows the value in the field, not only the stored one", async () => {
    setup(strategy({ allocation_percent: "2" }), { preview: served(SMALL_POOL) });
    await expectText(amountLine("6.00"));
    expect(screen.queryByText(WARNING)).toBeNull();

    moveHandle("Home");
    expect(screen.queryByText(WARNING)).toBeInTheDocument();
    fireEvent.click(stop(50));
    expect(screen.queryByText(WARNING)).toBeNull();
  });

  it("Save stays enabled while it shows, and the request is sent", async () => {
    const { patches } = setup(strategy({ allocation_percent: "10" }), { preview: served(SMALL_POOL) });
    await expectText(amountLine("30.00"));

    type("1");

    expect(screen.queryByText(WARNING)).toBeInTheDocument();
    expect(saveButton()).toBeEnabled();
    expect(field()).toBeEnabled();
    expect(track()).toBeEnabled();
    fireEvent.click(saveButton());
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0]?.body).toBe('{"allocation_percent":"1"}');
  });

  it("an amount exactly at the minimum is not warned about", async () => {
    setup(strategy({ allocation_percent: "1" }), { preview: served({ unit: 5, minimum: "5.000000000000000000" }) });

    await expectText(amountLine("5.00"));
    expect(screen.queryByText(/less than the pool's minimum order/)).toBeNull();
  });

  it("a share the pool's minimum accepts shows no warning, and neither does one too small for a pair: the panel checks no pair", async () => {
    const { previews, requests } = setup(strategy({ allocation_percent: "1" }), {
      preview: served({ unit: 10, minimum: "5.000000000000000000" }),
    });

    await expectText(amountLine("10.00"));

    expect(screen.queryByText(/less than the pool's minimum order/)).toBeNull();
    expect(saveButton()).toBeDisabled();
    type("2");
    expect(saveButton()).toBeEnabled();
    expect(previews).toEqual([null]);
    expect(requests).toEqual([]);
  });

  it("no balance, no figure, no warning", async () => {
    setup(strategy({ allocation_percent: "1" }), { preview: served({ noBalance: true }) });

    await expectText("The pool's balance has not been read yet, so the amount cannot be shown.");
    expect(screen.queryByText(/less than the pool's minimum order/)).toBeNull();
  });

  it("a balance that falls puts the warning on a stored share at the next read", async () => {
    let reads = 0;
    const { client } = setup(strategy({ allocation_percent: "2" }), {
      preview: () => jsonResponse(previewBody(++reads === 1 ? { unit: 3, minimum: "5.000000000000000000" } : { unit: 2, minimum: "5.000000000000000000" })),
    });
    await expectText(amountLine("6.00"));
    expect(screen.queryByText(WARNING)).toBeNull();

    await act(() => client.invalidateQueries({ queryKey: ["strategy", ID, "share-preview"] }));

    await expectText(amountLine("4.00"));
    expect(screen.queryByText(WARNING)).toBeInTheDocument();
  });

  it("the warning reads in Spanish when the language is", async () => {
    await i18n.changeLanguage("es");
    try {
      setup(strategy({ allocation_percent: "1" }), { preview: served(SMALL_POOL) });

      await expectText(
        "Con este saldo, el porcentaje pide menos que la orden mínima del pool, 5,00 USDT. Las aperturas se omitirían hasta que el porcentaje o el saldo sean mayores.",
      );
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });

  describe("for a typed decimal", () => {
    afterEach(() => {
      vi.useRealTimers();
    });

    it("it shows for a typed 0.5 once its answer arrives and not while loading", async () => {
      const { preview, answer } = heldPreview({ unit: 10, minimum: "5.000000000000000000" });
      setup(strategy(), { preview });
      await expectText(amountLine("300.00"));
      vi.useFakeTimers();

      type("0.5");
      await tick(300);
      expect(screen.queryByText(LOADING)).toBeInTheDocument();
      expect(screen.queryByText(/less than the pool's minimum order/)).toBeNull();

      answer("0.5", "1.500000000000000000", "0.5", true);
      await tick(0);

      expect(screen.queryByText(amountLine("1.50"))).toBeInTheDocument();
      expect(
        screen.queryByText(
          "At this balance the share asks for less than the pool's minimum order, 5.00 USDT. Openings would be skipped until the share or the balance is larger.",
        ),
      ).toBeInTheDocument();
      expect(saveButton()).toBeEnabled();
    });

    it("the warning of the value before it is gone while the next value loads", async () => {
      const { preview, answer } = heldPreview({ unit: 10, minimum: "5.000000000000000000" });
      setup(strategy(), { preview });
      await expectText(amountLine("300.00"));
      vi.useFakeTimers();
      type("0.5");
      await tick(300);
      answer("0.5", "1.500000000000000000", "0.5", true);
      await tick(0);
      expect(screen.queryByText(/less than the pool's minimum order/)).toBeInTheDocument();

      type("0.6");

      expect(screen.queryByText(/less than the pool's minimum order/)).toBeNull();
    });
  });
});

const SHARE_INFO = "About the share of the pool";
const AMOUNT_INFO = "About this amount and what is not checked";
const HINT =
  "Each new operation asks for this share of the pool's total balance. A change applies from the next operation; one already open keeps its size.";
const ESTIMATE =
  "An estimate: this share of the pool's total balance, read at 14:03 UTC. The balance is read again when an operation opens, and the pool grants less when less is free. It is margin; the position is this amount times the account's leverage.";
const PAIR_NOTE =
  "Each pair also has a minimum order at the exchange, which depends on its price and on the account's leverage. The panel does not check it. A signal whose order would be too small is refused and nothing is opened.";

const shareInfo = () => screen.getByRole("button", { name: SHARE_INFO });
const amountInfo = () => screen.getByRole("button", { name: AMOUNT_INFO });
const expandedOf = (button: HTMLElement) => button.getAttribute("aria-expanded");
/** Whether `before` comes before `after` in the document, which is the order on screen. */
const precedes = (before: Element, after: Element) =>
  (before.compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;

describe("PoolShareEditor, the two information buttons", () => {
  it("both buttons are present and closed, and none of the three explanatory sentences is in the document", async () => {
    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));

    expect(screen.queryByRole("button", { name: SHARE_INFO })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: AMOUNT_INFO })).toBeInTheDocument();
    expect(expandedOf(shareInfo())).toBe("false");
    expect(expandedOf(amountInfo())).toBe("false");
    expect(screen.queryByText(HINT)).toBeNull();
    expect(screen.queryByText(ESTIMATE)).toBeNull();
    expect(screen.queryByText(PAIR_NOTE)).toBeNull();
  });

  it("none of the three sentences is in the document in Spanish either", async () => {
    await i18n.changeLanguage("es");
    try {
      setup(strategy(), { preview: served() });
      await expectText("Pide alrededor de 300,00 USDT por operación");

      expect(screen.queryByRole("button", { name: "Acerca del porcentaje del pool" })).toBeInTheDocument();
      expect(screen.queryByText(/Cada nueva operación pide/)).toBeNull();
      expect(screen.queryByText(/Es una estimación/)).toBeNull();
      expect(screen.queryByText(/Cada par tiene además/)).toBeNull();
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });

  it("each button points at a container that is in the document while it is closed", async () => {
    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));

    for (const button of [shareInfo(), amountInfo()]) {
      const container = document.getElementById(button.getAttribute("aria-controls") ?? "");
      expect(container).toBeInTheDocument();
      expect(container).toBeEmptyDOMElement();
      expect(container).toHaveClass("empty:hidden");
    }
  });

  it("the label's button shows the hint and only that, under the label's row, in the flow", async () => {
    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));

    fireEvent.click(shareInfo());

    expect(expandedOf(shareInfo())).toBe("true");
    expect(screen.queryByText(HINT)).toBeInTheDocument();
    expect(screen.queryByText(ESTIMATE)).toBeNull();
    expect(screen.queryByText(PAIR_NOTE)).toBeNull();
    expect(precedes(shareInfo(), screen.getByText(HINT))).toBe(true);
    expect(precedes(screen.getByText(HINT), field())).toBe(true);
    expect(screen.getByText(HINT).closest("[popover]")).toBeNull();
  });

  it("the amount's button shows the estimate with the time as HH:MM UTC, then the pair note, in that order", async () => {
    setup(strategy(), { preview: served({ observedAt: "2026-10-09T14:03:12Z" }) });
    await expectText(amountLine("300.00"));

    fireEvent.click(amountInfo());

    expect(expandedOf(amountInfo())).toBe("true");
    expect(screen.queryByText(HINT)).toBeNull();
    expect(screen.queryByText(ESTIMATE)).toBeInTheDocument();
    expect(screen.queryByText(PAIR_NOTE)).toBeInTheDocument();
    expect(precedes(screen.getByText(ESTIMATE), screen.getByText(PAIR_NOTE))).toBe(true);
    expect(precedes(screen.getByText(amountLine("300.00")), screen.getByText(ESTIMATE))).toBe(true);
    expect(screen.getByText(ESTIMATE).closest("[popover]")).toBeNull();
  });

  it("with no balance read, the amount's button shows the pair note only: there is no time to name", async () => {
    setup(strategy(), { preview: served({ noBalance: true }) });
    await expectText("The pool's balance has not been read yet, so the amount cannot be shown.");

    fireEvent.click(amountInfo());

    expect(screen.queryByText(PAIR_NOTE)).toBeInTheDocument();
    expect(screen.queryByText(/An estimate/)).toBeNull();
  });

  it("the explanations read in Spanish with the time as HH:MM UTC", async () => {
    await i18n.changeLanguage("es");
    try {
      setup(strategy(), { preview: served({ observedAt: "2026-10-09T14:03:12Z" }) });
      await expectText("Pide alrededor de 300,00 USDT por operación");

      fireEvent.click(screen.getByRole("button", { name: "Acerca de este importe y de lo que no se comprueba" }));

      expect(
        screen.queryByText(
          "Es una estimación: este porcentaje del saldo total del pool, leído a las 14:03 UTC. El saldo se vuelve a leer cuando se abre una operación, y el pool concede menos cuando hay menos disponible. Es margen; la posición es este importe por el apalancamiento de la cuenta.",
        ),
      ).toBeInTheDocument();
      expect(
        screen.queryByText(
          "Cada par tiene además una orden mínima en el exchange, que depende de su precio y del apalancamiento de la cuenta. El panel no la comprueba. Una señal cuya orden fuera demasiado pequeña se rechaza y no se abre nada.",
        ),
      ).toBeInTheDocument();
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });

  it("the stale line, the warning, the validation text and a refused save are in the document with both buttons closed", async () => {
    setup(strategy({ allocation_percent: "1" }), {
      preview: served({ unit: 3, minimum: "5.000000000000000000", stale: true, observedAt: "2026-10-09T14:03:12Z" }),
      patch: refuse(500, "boom"),
    });
    await expectText(amountLine("3.00"));

    expect(expandedOf(shareInfo())).toBe("false");
    expect(expandedOf(amountInfo())).toBe("false");
    expect(screen.queryByText("The pool's balance was last read at 14:03 UTC and may be out of date.")).toBeInTheDocument();
    expect(screen.queryByText(/less than the pool's minimum order/)).toBeInTheDocument();
    type("abc");
    expect(screen.queryByText("Enter a number, for example 25 or 33.5.")).toBeInTheDocument();
    type("2");
    fireEvent.click(saveButton());
    expect(await alertLine()).toHaveTextContent("The share was not saved. Try again.");
    expect(expandedOf(shareInfo())).toBe("false");
  });

  it("the unreadable stored value is in the document with the buttons closed", () => {
    setup(strategy({ allocation_percent: "1E-7" }), { preview: served() });

    expect(screen.queryByText("The stored share could not be read, so it cannot be edited here.")).toBeInTheDocument();
  });

  it("both can be open together, and each closes only its own text", async () => {
    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));

    fireEvent.click(shareInfo());
    fireEvent.click(amountInfo());
    expect(screen.queryByText(HINT)).toBeInTheDocument();
    expect(screen.queryByText(ESTIMATE)).toBeInTheDocument();

    fireEvent.click(shareInfo());
    expect(screen.queryByText(HINT)).toBeNull();
    expect(screen.queryByText(ESTIMATE)).toBeInTheDocument();
  });

  it("Escape closes the text from the button or from inside it and leaves focus on the button", async () => {
    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));
    fireEvent.click(amountInfo());

    fireEvent.keyDown(screen.getByText(ESTIMATE), { key: "Escape" });

    expect(screen.queryByText(ESTIMATE)).toBeNull();
    expect(amountInfo()).toHaveFocus();
  });

  it("moving the handle or the focus does not close an open explanation", async () => {
    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));
    fireEvent.click(shareInfo());

    moveHandle("ArrowRight");
    field().focus();
    type("40");

    expect(screen.queryByText(HINT)).toBeInTheDocument();
  });

  it("an open explanation survives a save", async () => {
    setupPage(strategy(), { preview: served() });
    await screen.findByRole("textbox");
    await expectText(amountLine("300.00"));
    fireEvent.click(amountInfo());

    type("40");
    fireEvent.click(saveButton());
    await waitFor(() => expect(savedRegion()).toHaveTextContent("Saved"));

    expect(screen.queryByText(ESTIMATE)).toBeInTheDocument();
  });

  it("an open explanation survives a refused save", async () => {
    setup(strategy(), { preview: served(), patch: refuse(500, "boom") });
    await expectText(amountLine("300.00"));
    fireEvent.click(shareInfo());

    type("40");
    fireEvent.click(saveButton());
    await alertLine();

    expect(screen.queryByText(HINT)).toBeInTheDocument();
  });

  it("an open explanation survives a change of language, and is then the Spanish text", async () => {
    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));
    fireEvent.click(shareInfo());

    await act(() => i18n.changeLanguage("es"));
    try {
      expect(screen.queryByText(/Cada nueva operación pide este porcentaje del saldo total del pool/)).toBeInTheDocument();
      expect(screen.queryByText(HINT)).toBeNull();
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });

  it("both buttons are enabled on an archived strategy, and open", async () => {
    setup(strategy({ archived_at: "2026-10-01T00:00:00Z" }), { preview: served() });
    await expectText(amountLine("300.00"));

    expect(shareInfo()).toBeEnabled();
    expect(amountInfo()).toBeEnabled();
    fireEvent.click(shareInfo());
    fireEvent.click(amountInfo());
    expect(screen.queryByText(HINT)).toBeInTheDocument();
    expect(screen.queryByText(PAIR_NOTE)).toBeInTheDocument();
  });

  it("both buttons are enabled while a save is in flight", async () => {
    setup(strategy(), { preview: served(), patch: () => new Promise<Response>(() => undefined) });
    await expectText(amountLine("300.00"));
    type("40");
    fireEvent.click(saveButton());
    await screen.findByRole("button", { name: "Saving…" });

    expect(shareInfo()).toBeEnabled();
    expect(amountInfo()).toBeEnabled();
    fireEvent.click(amountInfo());
    expect(screen.queryByText(PAIR_NOTE)).toBeInTheDocument();
  });

  it("the amount's button is present with a figure, with the em dash, with no balance and with a failed read", async () => {
    const present = () => expect(screen.queryByRole("button", { name: AMOUNT_INFO })).toBeInTheDocument();

    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));
    present();
    type("abc");
    expect(screen.queryByText("—")).toBeInTheDocument();
    present();
  });

  it.each([
    ["no balance", { preview: served({ noBalance: true }) }, "The pool's balance has not been read yet, so the amount cannot be shown."],
    ["a failed read", { preview: () => jsonResponse({ detail: "boom" }, 500) }, "The amount could not be loaded."],
  ])("the amount's button is present with %s", async (_name, options, text) => {
    setup(strategy(), options);

    await expectText(text);

    expect(screen.queryByRole("button", { name: AMOUNT_INFO })).toBeInTheDocument();
    expect(amountInfo()).toBeEnabled();
  });

  it("Tab goes: the label's button, the field, the track, 25, 50, 75, 100, the amount's button, Save", async () => {
    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));
    type("40");
    expect(saveButton()).toBeEnabled();

    const visited: Array<Element | null> = [];
    for (let stopNumber = 0; stopNumber < 9; stopNumber += 1) {
      act(() => {
        pressTab();
      });
      visited.push(document.activeElement);
    }

    expect(visited).toEqual([
      shareInfo(),
      field(),
      track(),
      stop(25),
      stop(50),
      stop(75),
      stop(100),
      amountInfo(),
      saveButton(),
    ]);
  });

  it("with Save disabled the order ends at the amount's button: a disabled button is no stop", async () => {
    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));
    expect(saveButton()).toBeDisabled();

    const visited: Array<Element | null> = [];
    for (let stopNumber = 0; stopNumber < 9; stopNumber += 1) {
      act(() => {
        pressTab();
      });
      visited.push(document.activeElement);
    }

    // Eight stops, and the ninth press wraps to the first.
    expect(visited.slice(0, 8)).toEqual([shareInfo(), field(), track(), stop(25), stop(50), stop(75), stop(100), amountInfo()]);
    expect(visited[8]).toBe(shareInfo());
  });

  it("the stored 33.5 is read as '33.5% of the pool' with the handle at 34", async () => {
    setup(strategy({ allocation_percent: "33.5" }), {
      preview: served({ exact: { share: "33.5", amount: "335.000000000000000000" } }),
    });
    await expectText(amountLine("335.00"));

    expect(track()).toHaveAttribute("aria-valuetext", "33.5% of the pool");
    expect(track().value).toBe("34");
  });

  it("no element carries a style attribute", async () => {
    const { requests } = setup(strategy({ allocation_percent: "1" }), {
      preview: served({ unit: 3, minimum: "5.000000000000000000", stale: true }),
    });
    await expectText(amountLine("3.00"));
    fireEvent.click(shareInfo());
    fireEvent.click(amountInfo());

    expect(document.body.querySelectorAll("[style]")).toHaveLength(0);
    expect(requests).toEqual([]);
  });
});

/**
 * Every text of design § I that this control writes, in both languages, as the design has it with the
 * example values of the state it is shown in. The table is held here and not read from the locale files, so
 * a reworded value is red. A Spanish text left in English equals its English twin, so each Spanish text is
 * required by name below, never by comparison with the English one.
 */
const SHARE_TEXTS = {
  label: { en: "Share of the pool per trade", es: "Porcentaje del pool por operación" },
  info: { en: "About the share of the pool", es: "Acerca del porcentaje del pool" },
  hint: {
    en: "Each new operation asks for this share of the pool's total balance. A change applies from the next operation; one already open keeps its size.",
    es: "Cada nueva operación pide este porcentaje del saldo total del pool. Un cambio se aplica desde la próxima operación; una ya abierta mantiene su tamaño.",
  },
  amountInfo: { en: "About this amount and what is not checked", es: "Acerca de este importe y de lo que no se comprueba" },
  amount: { en: "Asks for about 300.00 USDT per operation", es: "Pide alrededor de 300,00 USDT por operación" },
  amountHint: {
    en: "An estimate: this share of the pool's total balance, read at 14:03 UTC. The balance is read again when an operation opens, and the pool grants less when less is free. It is margin; the position is this amount times the account's leverage.",
    es: "Es una estimación: este porcentaje del saldo total del pool, leído a las 14:03 UTC. El saldo se vuelve a leer cuando se abre una operación, y el pool concede menos cuando hay menos disponible. Es margen; la posición es este importe por el apalancamiento de la cuenta.",
  },
  amountStale: {
    en: "The pool's balance was last read at 14:03 UTC and may be out of date.",
    es: "El saldo del pool se leyó por última vez a las 14:03 UTC y puede estar desactualizado.",
  },
  amountNoBalance: {
    en: "The pool's balance has not been read yet, so the amount cannot be shown.",
    es: "El saldo del pool todavía no se ha leído, por lo que no se puede mostrar el importe.",
  },
  amountLoading: { en: "Calculating the amount…", es: "Calculando el importe…" },
  amountError: { en: "The amount could not be loaded.", es: "No se pudo cargar el importe." },
  belowPoolMinimum: {
    en: "At this balance the share asks for less than the pool's minimum order, 5.00 USDT. Openings would be skipped until the share or the balance is larger.",
    es: "Con este saldo, el porcentaje pide menos que la orden mínima del pool, 5,00 USDT. Las aperturas se omitirían hasta que el porcentaje o el saldo sean mayores.",
  },
  pairMinimumNote: {
    en: "Each pair also has a minimum order at the exchange, which depends on its price and on the account's leverage. The panel does not check it. A signal whose order would be too small is refused and nothing is opened.",
    es: "Cada par tiene además una orden mínima en el exchange, que depende de su precio y del apalancamiento de la cuenta. El panel no la comprueba. Una señal cuya orden fuera demasiado pequeña se rechaza y no se abre nada.",
  },
  valueText: { en: "30% of the pool", es: "30 % del pool" },
  stop: { en: "Set the share to 50%", es: "Fijar el porcentaje en 50 %" },
  notNumber: { en: "Enter a number, for example 25 or 33.5.", es: "Escriba un número, por ejemplo 25 o 33,5." },
  outOfRange: {
    en: "The share must be above 0 and at most 100.",
    es: "El porcentaje debe ser mayor que 0 y como máximo 100.",
  },
  save: { en: "Save share", es: "Guardar porcentaje" },
  saving: { en: "Saving…", es: "Guardando…" },
  saveFailed: { en: "The share was not saved. Try again.", es: "El porcentaje no se guardó. Inténtelo de nuevo." },
  archived: {
    en: "This strategy is archived and can no longer be changed.",
    es: "Esta estrategia está archivada y ya no se puede modificar.",
  },
  gone: { en: "This strategy no longer exists.", es: "Esta estrategia ya no existe." },
  unreadable: {
    en: "The stored share could not be read, so it cannot be edited here.",
    es: "No se pudo leer el porcentaje guardado, por lo que no se puede editar aquí.",
  },
  // The owner's own words (decision 48).
  saved: { en: "Saved", es: "Guardado" },
} as const;

describe.each(["en", "es"] as const)("PoolShareEditor, every text of design § I, in %s", (language) => {
  const T = Object.fromEntries(Object.entries(SHARE_TEXTS).map(([key, texts]) => [key, texts[language]])) as Record<
    keyof typeof SHARE_TEXTS,
    string
  >;
  const named = (name: string) => screen.getByRole("button", { name });
  const here = (text: string) => expect(screen.queryByText(text)).toBeInTheDocument();
  const hereLater = (text: string) => waitFor(() => here(text));

  beforeEach(async () => {
    await act(() => i18n.changeLanguage(language));
  });
  afterEach(async () => {
    await act(() => i18n.changeLanguage("en"));
  });

  it("the label, the two buttons' names, the amount, the track's reading, a stop and Save", async () => {
    setup(strategy(), { preview: served({ observedAt: "2026-10-09T14:03:12Z" }) });
    await hereLater(T.amount);

    here(T.label);
    named(T.info);
    named(T.amountInfo);
    expect(screen.getByRole("slider", { name: T.label })).toHaveAttribute("aria-valuetext", T.valueText);
    named(T.stop);
    named(T.save);
  });

  it("the hint is behind the label's button, and the estimate and the pair note behind the amount's", async () => {
    setup(strategy(), { preview: served({ observedAt: "2026-10-09T14:03:12Z" }) });
    await hereLater(T.amount);

    fireEvent.click(named(T.info));
    here(T.hint);
    fireEvent.click(named(T.amountInfo));
    here(T.amountHint);
    here(T.pairMinimumNote);
  });

  it("the stale line", async () => {
    setup(strategy(), { preview: served({ stale: true, observedAt: "2026-10-09T14:03:12Z" }) });

    await hereLater(T.amountStale);
  });

  it("no balance, loading and a failed read", async () => {
    setup(strategy(), { preview: served({ noBalance: true }) });
    await hereLater(T.amountNoBalance);
    cleanup();

    setup(strategy(), { preview: () => new Promise<Response>(() => undefined) });
    await hereLater(T.amountLoading);
    cleanup();

    setup(strategy(), { preview: () => jsonResponse({ detail: "boom" }, 500) });
    await hereLater(T.amountError);
  });

  it("the warning on the pool's minimum", async () => {
    setup(strategy({ allocation_percent: "1" }), { preview: served({ unit: 3, minimum: "5.000000000000000000" }) });

    await hereLater(T.belowPoolMinimum);
  });

  it("the two refusals of a typed value", async () => {
    setup(strategy());

    type("abc");
    here(T.notNumber);
    type("0");
    here(T.outOfRange);
  });

  it("Saving…, the failure, the archived refusal and the missing strategy", async () => {
    setup(strategy(), { patch: () => new Promise<Response>(() => undefined) });
    type("40");
    fireEvent.click(named(T.save));
    await waitFor(() => named(T.saving));
    cleanup();

    setup(strategy(), { patch: refuse(500, "boom") });
    type("40");
    fireEvent.click(named(T.save));
    await alertLine();
    here(T.saveFailed);
    cleanup();

    setup(strategy(), { patch: refuse(409, { error: "STRATEGY_ARCHIVED", message: "archived" }) });
    type("40");
    fireEvent.click(named(T.save));
    await alertLine();
    here(T.archived);
    cleanup();

    setup(strategy(), { patch: refuse(404, "no such strategy") });
    type("40");
    fireEvent.click(named(T.save));
    await alertLine();
    here(T.gone);
  });

  it("the unreadable stored share", () => {
    setup(strategy({ allocation_percent: "1E-7" }));

    here(T.unreadable);
  });

  // Re-pointed: "Saved" is the button's own text now, and it is also said by the status region, so the text
  // alone is on screen twice (one of them hidden from sight).
  it("Saved", async () => {
    setup(strategy());
    type("40");
    fireEvent.click(named(T.save));

    const button = await waitFor(() => named(T.saved));
    expect(button.parentElement?.querySelector('[role="status"]')).toHaveTextContent(T.saved);
  });
});

/** The class tokens of an element, so a test names a class and not a substring of the whole attribute. */
const classesOf = (element: Element) => element.className.split(/\s+/);

/** The nearest element that holds both nodes: the row they share. */
function sharedRow(first: Element, second: Element): HTMLElement {
  let node: HTMLElement | null = first.parentElement;
  while (node !== null && !node.contains(second)) node = node.parentElement;
  if (node === null) throw new Error("the two nodes share no row");
  return node;
}

/** The direct child of `row` that holds `node`. */
function childHolding(row: HTMLElement, node: Element): HTMLElement {
  const child = Array.from(row.children).find((candidate) => candidate.contains(node));
  if (child === undefined) throw new Error("no child of the row holds the node");
  return child as HTMLElement;
}

describe("PoolShareEditor, Save sits to the right of the amount block (12f.10.30c)", () => {
  it("Save and the amount line share one horizontal row, aligned to the top, that does not wrap", async () => {
    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));

    const row = sharedRow(saveButton(), screen.getByText(amountLine("300.00")));

    expect(classesOf(row)).toEqual(expect.arrayContaining(["flex", "items-start"]));
    expect(classesOf(row)).not.toContain("flex-col");
    expect(classesOf(row)).not.toContain("flex-wrap");
    // The row is the amount block and the button block, not the whole control.
    expect(row.contains(field())).toBe(false);
    expect(row.children).toHaveLength(2);
  });

  it("the left block is the amount line with its information button, and it takes the room that is left", async () => {
    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));
    const row = sharedRow(saveButton(), screen.getByText(amountLine("300.00")));

    const text = childHolding(row, screen.getByText(amountLine("300.00")));

    expect(text.contains(amountInfo())).toBe(true);
    expect(text.contains(saveButton())).toBe(false);
    expect(classesOf(text)).toEqual(expect.arrayContaining(["min-w-0", "flex-1"]));
  });

  // Edited by 12f.10.30d: "Saved" is no longer a text before the button; the button holds it, and the
  // status region that announces it follows the button.
  it("the right block is Save and then its status, keeps its size and is aligned to the top", async () => {
    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));
    const row = sharedRow(saveButton(), screen.getByText(amountLine("300.00")));

    const actions = childHolding(row, saveButton());
    const status = actions.querySelector<HTMLElement>('[role="status"]');

    expect(actions).not.toBe(childHolding(row, screen.getByText(amountLine("300.00"))));
    expect(classesOf(actions)).toEqual(expect.arrayContaining(["flex", "items-start", "shrink-0"]));
    expect(classesOf(actions)).not.toContain("flex-wrap");
    expect(status).not.toBeNull();
    expect(precedes(saveButton(), status as HTMLElement)).toBe(true);
    expect(saveButton().className).toContain("min-h-11");
  });

  it("the text block comes first in the document: the amount, then Save, then its status", async () => {
    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));
    const row = sharedRow(saveButton(), screen.getByText(amountLine("300.00")));

    expect(precedes(screen.getByText(amountLine("300.00")), saveButton())).toBe(true);
    expect(precedes(amountInfo(), saveButton())).toBe(true);
    expect(precedes(saveButton(), savedRegion())).toBe(true);
    expect(row.firstElementChild).toBe(childHolding(row, screen.getByText(amountLine("300.00"))));
  });

  it("the explanation that opens under the amount stays in the left block, so Save does not move", async () => {
    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));
    const row = sharedRow(saveButton(), screen.getByText(amountLine("300.00")));
    const actionsBefore = childHolding(row, saveButton());

    fireEvent.click(amountInfo());

    const estimate = screen.getByText(ESTIMATE);
    const text = childHolding(row, screen.getByText(amountLine("300.00")));
    expect(text.contains(estimate)).toBe(true);
    expect(text.contains(screen.getByText(PAIR_NOTE))).toBe(true);
    expect(childHolding(row, saveButton())).toBe(actionsBefore);
    expect(classesOf(row)).toContain("items-start");
  });

  it("the warning on the pool's minimum stays in the left block", async () => {
    setup(strategy({ allocation_percent: "1" }), { preview: served(SMALL_POOL) });
    await expectText(WARNING);
    const row = sharedRow(saveButton(), screen.getByText(WARNING));

    const text = childHolding(row, screen.getByText(WARNING));

    expect(text.contains(screen.getByText(amountLine("3.00")))).toBe(true);
    expect(text.contains(saveButton())).toBe(false);
    expect(classesOf(row)).not.toContain("flex-col");
  });

  it("a failed save is an alert outside the row", async () => {
    setup(strategy(), { preview: served(), patch: refuse(500, "boom") });
    await expectText(amountLine("300.00"));
    const row = sharedRow(saveButton(), screen.getByText(amountLine("300.00")));
    type("40");

    fireEvent.click(saveButton());

    const alert = await alertLine();
    expect(row.contains(alert)).toBe(false);
    expect(row.parentElement?.contains(alert)).toBe(true);
  });

  it("the refusal of a typed value is outside the row, and Saved is still inside it", async () => {
    setup(strategy(), { preview: served() });
    await expectText(amountLine("300.00"));
    const row = sharedRow(saveButton(), screen.getByText(amountLine("300.00")));

    type("abc");

    const refusal = screen.getByText("Enter a number, for example 25 or 33.5.");
    expect(row.contains(refusal)).toBe(false);
    expect(row.contains(savedRegion())).toBe(true);
  });
});

// 12f.10.30d. jsdom has no layout, so the width rule is pinned by structure: every text the button can show
// is in the button, in one cell, and the ones not shown are hidden from sight and from assistive technology.
describe.each([
  { language: "en", save: "Save share", saving: "Saving…", saved: "Saved" },
  { language: "es", save: "Guardar porcentaje", saving: "Guardando…", saved: "Guardado" },
] as const)("PoolShareEditor, Saved is the button's own text, in $language (12f.10.30d)", (T) => {
  beforeEach(async () => {
    await act(() => i18n.changeLanguage(T.language));
  });
  afterEach(async () => {
    await act(() => i18n.changeLanguage("en"));
  });

  const button = (name: string) => screen.getByRole("button", { name });
  const cellOf = (host: HTMLElement, text: string) => within(host).getByText(text);
  const isShown = (cell: HTMLElement) => !cell.hasAttribute("aria-hidden") && !classesOf(cell).includes("invisible");
  const isHidden = (cell: HTMLElement) =>
    cell.getAttribute("aria-hidden") === "true" && classesOf(cell).includes("invisible");
  /** Every element that holds exactly `text`, outside the button that owns it. */
  const outside = (host: HTMLElement, text: string) => screen.queryAllByText(text).filter((node) => !host.contains(node));

  it("holds all three of its texts and shows only Save while nothing was saved", () => {
    setup(strategy());

    const host = button(T.save);

    expect(isShown(cellOf(host, T.save))).toBe(true);
    expect(isHidden(cellOf(host, T.saving))).toBe(true);
    expect(isHidden(cellOf(host, T.saved))).toBe(true);
  });

  it("reads Saved after a save, disabled, and shows only that one of its three texts", async () => {
    setup(strategy());
    type("40");
    fireEvent.click(button(T.save));

    const host = await screen.findByRole("button", { name: T.saved });

    expect(host).toBeDisabled();
    expect(screen.queryByRole("button", { name: T.save })).toBeNull();
    expect(isShown(cellOf(host, T.saved))).toBe(true);
    expect(isHidden(cellOf(host, T.save))).toBe(true);
    expect(isHidden(cellOf(host, T.saving))).toBe(true);
  });

  it("shows only Saving while a save is in flight", async () => {
    setup(strategy(), { patch: () => new Promise<Response>(() => undefined) });
    type("40");
    fireEvent.click(button(T.save));

    const host = await screen.findByRole("button", { name: T.saving });

    expect(host).toBeDisabled();
    expect(isShown(cellOf(host, T.saving))).toBe(true);
    expect(isHidden(cellOf(host, T.save))).toBe(true);
    expect(isHidden(cellOf(host, T.saved))).toBe(true);
  });

  it("leaves no visible Saved beside the button: the one text outside it is the hidden status", async () => {
    setup(strategy());
    type("40");
    fireEvent.click(button(T.save));
    const host = await screen.findByRole("button", { name: T.saved });

    const elsewhere = outside(host, T.saved);

    expect(elsewhere).toHaveLength(1);
    const status = elsewhere[0] as HTMLElement;
    expect(status).toHaveAttribute("role", "status");
    expect(classesOf(status)).toContain("sr-only");
    expect(host.parentElement).toContainElement(status);
  });

  it("goes back to Save when the value changes, and Saved is then in no visible text", async () => {
    setup(strategy());
    type("40");
    fireEvent.click(button(T.save));
    await screen.findByRole("button", { name: T.saved });

    type("41");

    const host = button(T.save);
    expect(host).toBeEnabled();
    expect(isShown(cellOf(host, T.save))).toBe(true);
    expect(isHidden(cellOf(host, T.saved))).toBe(true);
    expect(outside(host, T.saved)).toEqual([]);
  });
});
