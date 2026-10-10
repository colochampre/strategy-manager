import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PoolShareEditor } from "@/features/strategies/PoolShareEditor";
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

/** Every request the control makes, in order. A PATCH answers the strategy with the share it was sent. */
function setup(subject: Strategy) {
  const requests: Request[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    requests.push({ method: init?.method ?? "GET", path, body: typeof init?.body === "string" ? init.body : undefined });
    if (init?.method === "PATCH") {
      const sent = JSON.parse(String(init.body)) as { allocation_percent: string };
      return Promise.resolve(jsonResponse({ ...subject, allocation_percent: sent.allocation_percent }));
    }
    return Promise.resolve(jsonResponse({ detail: "not served by this test" }, 404));
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const ui = (current: Strategy) => (
    <QueryClientProvider client={client}>
      <PoolShareEditor strategy={current} />
    </QueryClientProvider>
  );
  const view = render(ui(subject));
  const patches = () => requests.filter((request) => request.method === "PATCH");
  return { requests, patches, rerender: (current: Strategy) => view.rerender(ui(current)), unmount: view.unmount };
}

/** The visible label, in the language in force, so the same helpers serve both languages. */
const label = () => i18n.t("strategies.detail.share.label");
const field = () => screen.getByRole("textbox", { name: label() }) as HTMLInputElement;
const track = () => screen.getByRole("slider", { name: label() }) as HTMLInputElement;
const stop = (value: number) => screen.getByRole("button", { name: `Set the share to ${value}%` });
const saveButton = () => screen.getByRole("button", { name: "Save share" });
const type = (text: string) => fireEvent.change(field(), { target: { value: text } });
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
  ])("%s leaves Save disabled", (_name, text) => {
    const { patches } = setup(strategy());

    type(text);

    expect(saveButton()).toBeDisabled();
    fireEvent.click(saveButton());
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

  it("no request is made before Save, whatever is moved, activated or typed", () => {
    const { requests } = setup(strategy());

    moveHandle("End");
    fireEvent.click(stop(25));
    type("12.5");
    type("abc");

    expect(requests).toEqual([]);
  });

  it("leaving the page after a change sends nothing", () => {
    const { requests, unmount } = setup(strategy());

    type("40");
    unmount();

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
