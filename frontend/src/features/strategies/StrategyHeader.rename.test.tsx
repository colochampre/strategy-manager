import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StrategyHeader } from "@/features/strategies/StrategyHeader";
import type { Strategy } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import { jsonResponse, lock, unlock } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";

const STRATEGY: Strategy = {
  id: ID,
  name: "ETH Breakout",
  exchange: "bybit",
  venue: "usdt-m",
  settlement_currency: "USDT",
  fill_mode: "SKIP",
  allocation_percent: "100",
  enabled: false,
  archived_at: null,
  allowed_pairs: ["ETHUSDT"],
  uptime: { seconds: 0, first_enabled_at: null, baseline: false },
};

interface Sent {
  url: string;
  method: string | undefined;
  body: unknown;
}

/** Answers every PATCH with `answer(name)`; records what was sent. */
function setup(strategy: Strategy = STRATEGY, answer: (name: string) => Response = (name) => jsonResponse({ ...strategy, name })) {
  const sent: Sent[] = [];
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => {
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as Record<string, unknown>) : undefined;
    sent.push({ url: String(input), method: init?.method, body });
    if (init?.method === "PATCH") return Promise.resolve(answer(String(body?.name)));
    return Promise.resolve(jsonResponse(strategy));
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <StrategyHeader strategy={strategy} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const patches = () => sent.filter((call) => call.method === "PATCH");
  return { queryClient, patches };
}

const pencil = () => screen.getByRole("button", { name: "Rename strategy" });
const field = () => screen.getByRole("textbox", { name: "Strategy name" });
const saveButton = () => screen.getByRole("button", { name: "Save name" });
const cancelButton = () => screen.getByRole("button", { name: "Cancel" });
const title = () => screen.queryByRole("heading", { level: 1 });

function type(text: string) {
  fireEvent.change(field(), { target: { value: text } });
}

beforeEach(unlock);
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

describe("StrategyHeader rename: the pencil (p21.2)", () => {
  it("puts a pencil button beside the title, with an aria-hidden icon", () => {
    setup();

    expect(title()).toHaveTextContent("ETH Breakout");
    expect(title()?.nextElementSibling).toBe(pencil());
    const svg = pencil().querySelector("svg");
    expect(svg).toHaveClass("lucide-pencil");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("opens a field holding the current name, focused, in place of the title", () => {
    setup();

    fireEvent.click(pencil());

    expect(field()).toHaveValue("ETH Breakout");
    expect(field()).toHaveFocus();
    expect(title()).toBeNull();
    expect(screen.queryByRole("button", { name: "Rename strategy" })).toBeNull();
    expect(saveButton()).toBeEnabled();
    expect(cancelButton()).toBeEnabled();
  });

  it("draws an aria-hidden Save icon on Save and an X on Cancel, each left of its text, the names unchanged (p21.5)", () => {
    setup();
    fireEvent.click(pencil());

    for (const [host, icon, name] of [
      [saveButton(), "lucide-save", "Save name"],
      [cancelButton(), "lucide-x", "Cancel"],
    ] as const) {
      const svg = host.querySelector("svg");
      expect(svg).toHaveClass(icon, "size-4", "shrink-0");
      expect(svg).toHaveAttribute("aria-hidden", "true");
      expect(host.firstElementChild).toBe(svg);
      expect(host).toHaveClass("inline-flex", "items-center", "gap-1.5");
      expect(host).toHaveAccessibleName(name);
    }
  });

  it("keeps Save as wide as its longest text: both texts share one cell, the hidden one out of sight and of the name (p21.5)", () => {
    setup();
    fireEvent.click(pencil());

    const cells = Array.from(saveButton().querySelectorAll("span > span"));
    expect(cells.map((cell) => cell.textContent)).toEqual(["Save name", "Saving…"]);
    expect(cells[1]).toHaveClass("invisible");
    expect(cells[1]).toHaveAttribute("aria-hidden", "true");
  });

  it("shows no pencil for an archived strategy", () => {
    setup({ ...STRATEGY, archived_at: "2026-10-01T00:00:00Z" });

    expect(title()).toHaveTextContent("ETH Breakout");
    expect(screen.queryByRole("button", { name: "Rename strategy" })).toBeNull();
  });

  it("is labelled in Spanish", async () => {
    await i18n.changeLanguage("es");
    setup();

    fireEvent.click(screen.getByRole("button", { name: "Renombrar estrategia" }));

    expect(screen.getByRole("textbox", { name: "Nombre de la estrategia" })).toHaveValue("ETH Breakout");
    expect(screen.getByRole("button", { name: "Guardar nombre" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeEnabled();
  });
});

describe("StrategyHeader rename: saving and cancelling (p21.3)", () => {
  it("sends the name with its edges trimmed, then closes the field and gives focus back to the pencil", async () => {
    const { patches } = setup();
    fireEvent.click(pencil());
    type("  ETH Breakout v2  ");

    fireEvent.click(saveButton());

    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(patches()).toEqual([{ url: expect.stringContaining(`/api/strategies/${ID}`), method: "PATCH", body: { name: "ETH Breakout v2" } }]);
    expect(pencil()).toHaveFocus();
  });

  it("saves on Enter", async () => {
    const { patches } = setup();
    fireEvent.click(pencil());
    type("Renamed");

    fireEvent.submit(field());

    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(patches().map((call) => call.body)).toEqual([{ name: "Renamed" }]);
  });

  it("cancels on Escape: the title is back unchanged and nothing is sent", () => {
    const { patches } = setup();
    fireEvent.click(pencil());
    type("Something else");

    fireEvent.keyDown(field(), { key: "Escape" });

    expect(screen.queryByRole("textbox")).toBeNull();
    expect(title()).toHaveTextContent("ETH Breakout");
    expect(pencil()).toHaveFocus();
    expect(patches()).toEqual([]);
  });

  it("cancels on Cancel: the title is back unchanged and nothing is sent", () => {
    const { patches } = setup();
    fireEvent.click(pencil());
    type("Something else");

    fireEvent.click(cancelButton());

    expect(screen.queryByRole("textbox")).toBeNull();
    expect(title()).toHaveTextContent("ETH Breakout");
    expect(patches()).toEqual([]);
  });

  it("opens again on the stored name, not on what was typed before a cancel", () => {
    setup();
    fireEvent.click(pencil());
    type("Something else");
    fireEvent.click(cancelButton());

    fireEvent.click(pencil());

    expect(field()).toHaveValue("ETH Breakout");
  });

  it.each(["", "   "])("disables Save while the trimmed name is empty (%j), and Enter sends nothing", (text) => {
    const { patches } = setup();
    fireEvent.click(pencil());
    type(text);

    expect(saveButton()).toBeDisabled();
    fireEvent.submit(field());

    expect(field()).toBeInTheDocument();
    expect(patches()).toEqual([]);
  });

  it("closes without a call when the trimmed name is unchanged", () => {
    const { patches } = setup();
    fireEvent.click(pencil());
    type(" ETH Breakout ");

    fireEvent.click(saveButton());

    expect(screen.queryByRole("textbox")).toBeNull();
    expect(patches()).toEqual([]);
  });

  it("disables both buttons while the rename is on its way", async () => {
    let release: (response: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    vi.stubGlobal("fetch", () => pending);
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <StrategyHeader strategy={STRATEGY} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(pencil());
    type("Renamed");

    fireEvent.click(saveButton());

    await waitFor(() => expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled());
    expect(cancelButton()).toBeDisabled();
    release(jsonResponse({ ...STRATEGY, name: "Renamed" }));
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
  });
});

describe("StrategyHeader rename: the refusals (p21.4)", () => {
  it.each([
    ["a name in use (409)", () => jsonResponse({ detail: "a strategy named 'Taken' already exists" }, 409), "A strategy with this name already exists."],
    [
      "an archived strategy (409 STRATEGY_ARCHIVED)",
      () => jsonResponse({ detail: { error: "STRATEGY_ARCHIVED", message: "archived" } }, 409),
      "This strategy is archived and can no longer be changed.",
    ],
    ["a strategy that is gone (404)", () => jsonResponse({ detail: "no strategy" }, 404), "This strategy no longer exists."],
    ["any other failure (500)", () => jsonResponse({ detail: "boom" }, 500), "The name was not saved. Try again."],
  ])("%s shows its text under the field, which stays open with what was typed", async (_case, answer, text) => {
    setup(STRATEGY, answer);
    fireEvent.click(pencil());
    type("Taken");

    fireEvent.click(saveButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(field()).toHaveValue("Taken");
    expect(field()).toHaveAttribute("aria-invalid", "true");
    expect(field()).toHaveAccessibleDescription(text);
    expect(saveButton()).toBeEnabled();
  });

  it("drops the refusal when the field is cancelled and opened again", async () => {
    setup(STRATEGY, () => jsonResponse({ detail: "taken" }, 409));
    fireEvent.click(pencil());
    type("Taken");
    fireEvent.click(saveButton());
    await screen.findByRole("alert");

    fireEvent.click(cancelButton());
    fireEvent.click(pencil());

    expect(screen.queryByRole("alert")).toBeNull();
    expect(field()).not.toHaveAttribute("aria-invalid", "true");
  });

  it("says a name in use in Spanish, with usted", async () => {
    await i18n.changeLanguage("es");
    setup(STRATEGY, () => jsonResponse({ detail: "taken" }, 409));
    fireEvent.click(screen.getByRole("button", { name: "Renombrar estrategia" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Nombre de la estrategia" }), { target: { value: "Taken" } });

    fireEvent.click(screen.getByRole("button", { name: "Guardar nombre" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Ya existe una estrategia con este nombre.");
  });

  it("says any other failure in Spanish, with usted", async () => {
    await i18n.changeLanguage("es");
    setup(STRATEGY, () => jsonResponse({ detail: "boom" }, 500));
    fireEvent.click(screen.getByRole("button", { name: "Renombrar estrategia" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Nombre de la estrategia" }), { target: { value: "Other" } });

    fireEvent.click(screen.getByRole("button", { name: "Guardar nombre" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("El nombre no se guardó. Inténtelo de nuevo.");
  });
});
