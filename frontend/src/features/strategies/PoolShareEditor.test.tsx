import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PoolShareEditor } from "@/features/strategies/PoolShareEditor";
import { useStrategy } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";
import { useTokenStore } from "@/shared/auth/token-store";
import i18n from "@/shared/i18n";
import { jsonResponse, pool } from "@/test/harness";
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
}

function previewBody(spec: PreviewSpec = {}) {
  const minimum = spec.minimum ?? "5.000000000000000000";
  const steps = Array.from({ length: spec.stepCount ?? 100 }, (_unused, index) => {
    const amount = 10 * (index + 1);
    return { share: index + 1, amount: `${amount}.000000000000000000`, below_pool_minimum: amount < Number(minimum) };
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

/** The live region beside Save, which is where "Saved" is written. */
function savedRegion(): HTMLElement {
  // The button reads "Saving…" while a save is in flight, so it is found by either name.
  const button = screen.getByRole("button", { name: /^(Save share|Saving…)$/ });
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
    // The fake clock is installed before the save, so a timer the control starts is a fake one too.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      await saveFortyOnAPage();

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
function heldPreview() {
  const held = new Map<string, (response: Response) => void>();
  const preview = (share: string | null) =>
    share === null
      ? jsonResponse(previewBody())
      : new Promise<Response>((resolve) => {
          held.set(share, resolve);
        });
  const answer = (share: string, amount: string, asked: string = share) =>
    held.get(share)?.(jsonResponse(previewBody({ exact: { share: asked, amount } })));
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
