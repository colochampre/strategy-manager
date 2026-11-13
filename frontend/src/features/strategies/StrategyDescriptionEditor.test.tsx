import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StrategyDescriptionEditor } from "@/features/strategies/StrategyDescriptionEditor";
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
    description: "Runs at 3x",
    subscribers: 1,
    live_subscribers: 0,
    created_at: null,
    capital: null,
    stop_loss_pct: "10.00",
    ...overrides,
  };
}

interface Sent {
  method: string;
  path: string;
  body: string | undefined;
}

interface Options {
  /** What the strategy's PATCH answers; by default 200 with the description trimmed as the server does. */
  patch?: () => Response;
}

/** The server holds the strategy; a PATCH of its description changes it. */
function stub(server: { strategy: Strategy }, options: Options) {
  const sent: Sent[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const method = init?.method ?? "GET";
      sent.push({ method, path, body: typeof init?.body === "string" ? init.body : undefined });
      if (method === "PATCH" && path === `/api/strategies/${ID}`) {
        if (options.patch !== undefined) return Promise.resolve(options.patch());
        const { description } = JSON.parse(String(init?.body)) as { description: string | null };
        const stored = description === null ? null : description.replace(/^[ \t\r\n]+|[ \t\r\n]+$/g, "");
        server.strategy = { ...server.strategy, description: stored === "" ? null : stored };
        return Promise.resolve(jsonResponse(server.strategy));
      }
      if (path === `/api/strategies/${ID}`) return Promise.resolve(jsonResponse(server.strategy));
      return Promise.resolve(jsonResponse({ detail: "not served by this test" }, 404));
    }),
  );
  return { patches: () => sent.filter((request) => request.method === "PATCH"), sent };
}

/** The editor as the page places it: the strategy comes from `useStrategy`, so a save's answer moves it. */
function Page() {
  const subject = useStrategy(ID);
  return subject.data === undefined ? <p>{subject.status}</p> : <StrategyDescriptionEditor strategy={subject.data} />;
}

function setupPage(subject: Strategy, options: Options = {}) {
  const served = stub({ strategy: subject }, options);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <Page />
    </QueryClientProvider>,
  );
  return { ...served, view };
}

/** The editor over a strategy handed in as a prop. */
function setupProp(subject: Strategy) {
  const served = stub({ strategy: subject }, {});
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <StrategyDescriptionEditor strategy={subject} />
    </QueryClientProvider>,
  );
  return served;
}

/** One task, so a request that would leave has had its chance before a test asserts that none did. */
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

const field = () => screen.getByRole("textbox", { name: "Description" }) as HTMLTextAreaElement;
const saveButton = () =>
  screen.getByRole("button", { name: /^Save$|^Saving…$|^Saved$/ }) as HTMLButtonElement;

async function ready() {
  await screen.findByRole("textbox", { name: "Description" });
}

describe("StrategyDescriptionEditor", () => {
  it("names the section at the size of the Share and Leverage names", async () => {
    setupPage(strategy());
    await ready();

    const name = screen.getByText("Description", { selector: "label" }).className.split(/\s+/);
    expect(name).toEqual(expect.arrayContaining(["text-sm", "leading-5", "text-ink-2"]));
    expect(name).not.toContain("text-xs");
    expect(name).not.toContain("font-semibold");
  });

  it("shows the stored description and a counter, with Save off", async () => {
    setupPage(strategy());
    await ready();

    expect(field().tagName).toBe("TEXTAREA");
    expect(field().value).toBe("Runs at 3x");
    expect(screen.getByText("10 / 2000")).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
    expect(saveButton()).toHaveAccessibleName("Save");
  });

  it("shows an empty field when there is no description", async () => {
    setupPage(strategy({ description: null }));
    await ready();

    expect(field().value).toBe("");
    expect(screen.getByText("0 / 2000")).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
  });

  it("sends nothing while the text is edited, and Save sends exactly the description as typed", async () => {
    const { patches } = setupPage(strategy());
    await ready();
    const typed = "  Recommended x5\nSecond line <b>x</b> ";

    fireEvent.change(field(), { target: { value: typed } });
    await nextTask();
    expect(saveButton()).toBeEnabled();
    expect(patches()).toHaveLength(0);

    fireEvent.click(saveButton());

    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0]?.body).toBe(JSON.stringify({ description: typed }));
    await waitFor(() => expect(saveButton()).toHaveAccessibleName("Saved"));
    expect(saveButton()).toBeDisabled();
    expect(field().value).toBe(typed);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("editing again after a save ends the Saved state", async () => {
    setupPage(strategy());
    await ready();
    fireEvent.change(field(), { target: { value: "Runs at 5x" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(saveButton()).toHaveAccessibleName("Saved"));

    fireEvent.change(field(), { target: { value: "Runs at 6x" } });

    expect(saveButton()).toHaveAccessibleName("Save");
    expect(saveButton()).toBeEnabled();
  });

  it("typing back the stored text, even padded as the server trims it, leaves Save off", async () => {
    const { patches } = setupPage(strategy());
    await ready();

    fireEvent.change(field(), { target: { value: "other" } });
    expect(saveButton()).toBeEnabled();
    fireEvent.change(field(), { target: { value: " \tRuns at 3x\r\n" } });
    expect(saveButton()).toBeDisabled();
    fireEvent.click(saveButton());
    await nextTask();

    expect(patches()).toHaveLength(0);
  });

  it("a non-breaking space is a change, as the server keeps it", async () => {
    setupPage(strategy());
    await ready();

    fireEvent.change(field(), { target: { value: "Runs at 3x " } });

    expect(saveButton()).toBeEnabled();
  });

  it("clearing the text saves null", async () => {
    const { patches } = setupPage(strategy());
    await ready();

    fireEvent.change(field(), { target: { value: " \n " } });
    expect(saveButton()).toBeEnabled();
    fireEvent.click(saveButton());

    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0]?.body).toBe('{"description":null}');
    await waitFor(() => expect(saveButton()).toHaveAccessibleName("Saved"));
  });

  it("a blank text over no description is no change", async () => {
    const { patches } = setupPage(strategy({ description: null }));
    await ready();

    fireEvent.change(field(), { target: { value: "  \n" } });
    fireEvent.click(saveButton());
    await nextTask();

    expect(saveButton()).toBeDisabled();
    expect(patches()).toHaveLength(0);
  });

  it("accepts 2,000 characters", async () => {
    const { patches } = setupPage(strategy());
    await ready();

    fireEvent.change(field(), { target: { value: "a".repeat(2000) } });

    expect(field()).not.toHaveAttribute("aria-invalid", "true");
    expect(saveButton()).toBeEnabled();
    fireEvent.click(saveButton());
    await waitFor(() => expect(patches()).toHaveLength(1));
  });

  it("refuses 2,001 characters in words and cannot be saved", async () => {
    const { patches } = setupPage(strategy());
    await ready();

    fireEvent.change(field(), { target: { value: "a".repeat(2001) } });

    expect(screen.getByText("2001 / 2000")).toBeInTheDocument();
    expect(field()).toHaveAttribute("aria-invalid", "true");
    expect(field()).toHaveAccessibleDescription("The description can have at most 2,000 characters.");
    expect(saveButton()).toBeDisabled();
    fireEvent.click(saveButton());
    await nextTask();
    expect(patches()).toHaveLength(0);
  });

  it("an ARCHIVED strategy is read-only", async () => {
    const { patches } = setupProp(strategy({ archived_at: "2026-10-01T00:00:00Z" }));

    expect(field()).toBeDisabled();
    expect(field().value).toBe("Runs at 3x");
    expect(saveButton()).toBeDisabled();
    await nextTask();
    expect(patches()).toHaveLength(0);
  });

  it.each([
    [422, { detail: "no" }, "The description is too long or holds a character that cannot be kept."],
    [409, { detail: "archived" }, "This strategy is archived, so its description can no longer be changed."],
    [404, { detail: "gone" }, "This strategy no longer exists."],
    [500, { detail: "boom" }, "The description was not saved. Try again."],
  ])("a refused save (%i) says why, in words of the panel", async (status, body, text) => {
    const { patches } = setupPage(strategy(), { patch: () => jsonResponse(body, status) });
    await ready();
    fireEvent.change(field(), { target: { value: "Runs at 8x" } });

    fireEvent.click(saveButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(patches()).toHaveLength(1);
    expect(saveButton()).toHaveAccessibleName("Save");
    expect(field().value).toBe("Runs at 8x");
  });

  it("the explanation is closed until its button opens it", async () => {
    setupPage(strategy());
    await ready();
    expect(screen.queryByText(/Anyone who opens this strategy sees it/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "About the description" }));

    expect(screen.getByText(/Anyone who opens this strategy sees it/)).toBeVisible();
  });

  it("reads in Spanish with the usted form", async () => {
    await i18n.changeLanguage("es");
    setupPage(strategy());

    expect(await screen.findByRole("textbox", { name: "Descripción" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar" })).toBeDisabled();
    expect(
      within(screen.getByRole("region", { name: "Descripción" })).getByRole("button", { name: "Guardar" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Acerca de la descripción" }));
    expect(screen.getByText(/Es un buen lugar para indicar qué apalancamiento recomienda/)).toBeVisible();
  });
});

describe("StrategyDescriptionEditor layout (L.7)", () => {
  it("puts the counter on the heading's row, beside the label and its information button", async () => {
    setupProp(strategy());
    await ready();

    const label = screen.getByText("Description", { selector: "label" });
    const counter = screen.getByText(/^\d+ \/ 2000$/);
    expect(counter.parentElement).toBe(label.parentElement);
    expect(counter).toHaveClass("ml-auto");
    expect(screen.getByRole("button", { name: "About the description" }).parentElement).toBe(label.parentElement);
  });

  it("puts Save on the right, under the field", async () => {
    setupProp(strategy());
    await ready();

    const row = saveButton().closest("div.flex") as HTMLElement;
    expect(row).toHaveClass("justify-end");
    expect(field().compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("draws Save as an icon with a tooltip, and keeps its name", async () => {
    setupProp(strategy());
    await ready();

    const button = saveButton();
    expect(button).toHaveTextContent("");
    fireEvent.mouseEnter(button.parentElement as HTMLElement);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Save");
  });
});
