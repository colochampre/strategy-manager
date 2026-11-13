import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StopLevelEditor } from "@/features/strategies/StopLevelEditor";
import { useStrategy } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import { jsonResponse, subscriptionOf } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: ID,
    name: "ETH Breakout",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    subscription: subscriptionOf(ID, "30"),
    enabled: false,
    archived_at: null,
    allowed_pairs: ["ETHUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    visibility: "PRIVATE",
    share_token: null,
    secret_last4: "x4F2",
    description: null,
    subscribers: 1,
    live_subscribers: 0,
    created_at: null,
    capital: null,
    stop_loss_pct: "10.00",
    ...overrides,
  };
}

interface Options {
  patch?: () => Response;
}

/** The server holds the strategy; a PATCH of its stop level changes it, written with two decimals as it does. */
function stub(server: { strategy: Strategy }, options: Options) {
  const patches: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const method = init?.method ?? "GET";
      if (method === "PATCH" && path === `/api/strategies/${ID}`) {
        patches.push(String(init?.body));
        if (options.patch !== undefined) return Promise.resolve(options.patch());
        const { stop_loss_pct: level } = JSON.parse(String(init?.body)) as { stop_loss_pct: string };
        server.strategy = { ...server.strategy, stop_loss_pct: Number(level).toFixed(2) };
        return Promise.resolve(jsonResponse(server.strategy));
      }
      if (path === `/api/strategies/${ID}`) return Promise.resolve(jsonResponse(server.strategy));
      return Promise.resolve(jsonResponse({ detail: "not served by this test" }, 404));
    }),
  );
  return { patches: () => patches };
}

/** The editor as the page places it: the strategy comes from `useStrategy`, so a save's answer moves it. */
function Page() {
  const subject = useStrategy(ID);
  return subject.data === undefined ? <p>{subject.status}</p> : <StopLevelEditor strategy={subject.data} />;
}

function setup(subject: Strategy, options: Options = {}) {
  const served = stub({ strategy: subject }, options);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Page />
    </QueryClientProvider>,
  );
  return served;
}

function nextTask() {
  return act(
    () =>
      new Promise<void>((resolve) => {
        setTimeout(resolve, 0);
      }),
  );
}

afterEach(async () => {
  cleanup();
  vi.unstubAllGlobals();
  await i18n.changeLanguage("en");
});

const field = () => screen.getByRole("textbox", { name: "Stop level" }) as HTMLInputElement;
const saveButton = () => screen.getByRole("button", { name: /^Save$|^Saving…$|^Saved$/ }) as HTMLButtonElement;

async function ready() {
  await screen.findByRole("textbox", { name: "Stop level" });
}

describe("StopLevelEditor", () => {
  it("shows the stored level as the server writes it, and Save off", async () => {
    setup(strategy());
    await ready();

    expect(field().value).toBe("10");
    expect(saveButton()).toBeDisabled();
  });

  // The leverage section on the same page already says what the level caps; the editor does not say it again.
  it("does not repeat what the level caps the leverage at", async () => {
    setup(strategy());
    await ready();

    expect(screen.queryByText(/Allows a leverage of up to/)).not.toBeInTheDocument();
  });

  it("sends nothing while it is edited, and Save sends exactly the level typed", async () => {
    const { patches } = setup(strategy());
    await ready();

    fireEvent.change(field(), { target: { value: "7.5" } });
    await nextTask();
    expect(patches()).toHaveLength(0);

    fireEvent.click(saveButton());

    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0]).toBe(JSON.stringify({ stop_loss_pct: "7.5" }));
    await waitFor(() => expect(saveButton()).toHaveAccessibleName("Saved"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each(["0.5", "60", "7.505", "abc", ""])("a level of %j is refused in the field and cannot be saved", async (typed) => {
    const { patches } = setup(strategy());
    await ready();

    fireEvent.change(field(), { target: { value: typed } });
    fireEvent.click(saveButton());
    await nextTask();

    expect(screen.getByText("Enter a percentage from 1 to 50, with at most two decimals.")).toBeInTheDocument();
    expect(field()).toHaveAttribute("aria-invalid", "true");
    expect(saveButton()).toBeDisabled();
    expect(patches()).toHaveLength(0);
  });

  it("typing back the stored level, written either way, leaves Save off", async () => {
    setup(strategy());
    await ready();

    fireEvent.change(field(), { target: { value: "12" } });
    expect(saveButton()).toBeEnabled();
    fireEvent.change(field(), { target: { value: "10.00" } });

    expect(saveButton()).toBeDisabled();
  });

  it("an archived strategy reads as it stands", async () => {
    setup(strategy({ archived_at: "2026-11-01T00:00:00Z" }));
    await ready();

    expect(field()).toBeDisabled();
    expect(saveButton()).toBeDisabled();
  });

  it("a refused save says so and leaves the stored level on screen", async () => {
    setup(strategy(), { patch: () => jsonResponse({ detail: "no" }, 500) });
    await ready();

    fireEvent.change(field(), { target: { value: "12" } });
    fireEvent.click(saveButton());

    expect(await screen.findByRole("alert")).toHaveTextContent("The stop level was not saved. Try again.");
  });

  it("speaks Spanish, in the formal register", async () => {
    await i18n.changeLanguage("es");
    setup(strategy());

    expect(await screen.findByRole("textbox", { name: "Nivel de stop" })).toBeInTheDocument();
    expect(screen.getByText("% del precio")).toBeInTheDocument();
  });
});

/** The class tokens of an element, so a test names a class and not a substring of the whole attribute. */
const classesOf = (element: Element) => element.className.split(/\s+/);

describe("StopLevelEditor layout, as Share and Leverage", () => {
  it("puts Save on the field's row: the field takes the width left, Save keeps its own", async () => {
    setup(strategy());
    await ready();

    let row: HTMLElement | null = saveButton().parentElement;
    while (row !== null && !row.contains(field())) row = row.parentElement;
    const holding = (node: Element) => Array.from(row!.children).find((child) => child.contains(node)) as HTMLElement;

    expect(classesOf(row!)).toEqual(expect.arrayContaining(["flex", "items-start"]));
    expect(classesOf(row!)).not.toContain("flex-col");
    expect(row!.children).toHaveLength(2);
    expect(classesOf(holding(field()))).toEqual(expect.arrayContaining(["min-w-0", "flex-1"]));
    expect(classesOf(holding(saveButton()))).toContain("shrink-0");
  });

  it("writes the unit right after the value, the input as wide as its text", async () => {
    setup(strategy());
    await ready();

    expect(field().nextElementSibling).toHaveTextContent("% of price");
    expect(classesOf(field())).toContain("field-sizing-content");
    expect(classesOf(field())).not.toContain("flex-1");
  });

  it("names the section at the size of the Share and Leverage names", async () => {
    setup(strategy());
    await ready();

    const name = screen.getByText("Stop level", { selector: "label" });
    expect(classesOf(name)).toEqual(expect.arrayContaining(["text-sm", "leading-5", "text-ink-2"]));
    expect(classesOf(name)).not.toContain("text-xs");
    expect(classesOf(name)).not.toContain("font-semibold");
  });
});
