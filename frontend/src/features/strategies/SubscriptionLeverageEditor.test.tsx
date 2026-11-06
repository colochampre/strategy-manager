import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SubscriptionLeverageEditor } from "@/features/strategies/SubscriptionLeverageEditor";
import { useStrategy } from "@/shared/api/strategies";
import type { Strategy, Subscription } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import { jsonResponse, subscriptionOf } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const SUBSCRIPTION_ID = "33333333-3333-4333-8333-333333333333";

const subscription = (leverage: number, overrides: Partial<Subscription> = {}) =>
  subscriptionOf(ID, "30", { id: SUBSCRIPTION_ID, leverage, ...overrides });

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: ID,
    name: "ETH Breakout",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    subscription: subscription(3),
    enabled: false,
    archived_at: null,
    allowed_pairs: ["ETHUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    visibility: "PRIVATE",
    secret_last4: "x4F2",
    subscribers: 1,
    live_subscribers: 0,
    capital: null,
    ...overrides,
  };
}

interface Sent {
  method: string;
  path: string;
  body: string | undefined;
}

interface Options {
  /** What the subscription's PATCH answers; by default 200 with the leverage it was sent. */
  patch?: () => Response;
}

/** The server holds the strategy; a PATCH of its subscription changes it. */
function stub(server: { strategy: Strategy }, options: Options) {
  const sent: Sent[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const method = init?.method ?? "GET";
      sent.push({ method, path, body: typeof init?.body === "string" ? init.body : undefined });
      if (method === "PATCH" && path === `/api/subscriptions/${SUBSCRIPTION_ID}`) {
        if (options.patch !== undefined) return Promise.resolve(options.patch());
        const { leverage } = JSON.parse(String(init?.body)) as { leverage: number };
        const saved = subscription(leverage);
        server.strategy = { ...server.strategy, subscription: saved };
        return Promise.resolve(jsonResponse(saved));
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
  return subject.data === undefined ? <p>{subject.status}</p> : <SubscriptionLeverageEditor strategy={subject.data} />;
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

/** The editor over a strategy handed in as a prop (for the states a save never reaches). */
function setupProp(subject: Strategy) {
  const served = stub({ strategy: subject }, {});
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <SubscriptionLeverageEditor strategy={subject} />
    </QueryClientProvider>,
  );
  return { ...served, view };
}

afterEach(async () => {
  cleanup();
  vi.unstubAllGlobals();
  await i18n.changeLanguage("en");
});

const field = () => screen.getByRole("textbox", { name: "Leverage" }) as HTMLInputElement;
const track = () => screen.getByRole("slider", { name: "Leverage" }) as HTMLInputElement;
const saveButton = () => screen.getByRole("button", { name: /^Save leverage$|^Saving…$|^Saved$/ }) as HTMLButtonElement;
const stopButton = (stop: number) => screen.getByRole("button", { name: `Set the leverage to x${stop}` });

async function ready() {
  await screen.findByRole("textbox", { name: "Leverage" });
}

describe("SubscriptionLeverageEditor", () => {
  it("shows the stored leverage in the field and on the range, with Save off", async () => {
    setupPage(strategy());
    await ready();

    expect(field().value).toBe("3");
    expect(track().value).toBe("3");
    expect(track()).toHaveAttribute("aria-valuetext", "x3");
    expect(saveButton()).toBeDisabled();
    expect(saveButton()).toHaveAccessibleName("Save leverage");
  });

  it("sends nothing while the value is edited, and Save sends exactly the leverage as a JSON number", async () => {
    const { patches } = setupPage(strategy());
    await ready();

    fireEvent.change(field(), { target: { value: "8" } });
    expect(track().value).toBe("8");
    expect(saveButton()).toBeEnabled();
    expect(patches()).toHaveLength(0);

    fireEvent.click(saveButton());

    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0]?.body).toBe('{"leverage":8}');
    await waitFor(() => expect(saveButton()).toHaveAccessibleName("Saved"));
    expect(saveButton()).toBeDisabled();
    expect(field().value).toBe("8");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("the range, a stop and the keyboard all move the field and the handle together", async () => {
    setupPage(strategy());
    await ready();

    fireEvent.change(track(), { target: { value: "12" } });
    expect(field().value).toBe("12");
    expect(track().value).toBe("12");

    fireEvent.click(stopButton(15));
    expect(field().value).toBe("15");
    expect(stopButton(15)).toHaveAttribute("aria-pressed", "true");

    fireEvent.change(field(), { target: { value: "7" } });
    expect(track().value).toBe("7");
  });

  it("changing the value again after a save ends the Saved state", async () => {
    setupPage(strategy());
    await ready();
    fireEvent.change(field(), { target: { value: "8" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(saveButton()).toHaveAccessibleName("Saved"));

    fireEvent.change(field(), { target: { value: "9" } });

    expect(saveButton()).toHaveAccessibleName("Save leverage");
    expect(saveButton()).toBeEnabled();
  });

  it("typing back the stored value leaves Save off", async () => {
    setupPage(strategy());
    await ready();

    fireEvent.change(field(), { target: { value: "8" } });
    fireEvent.change(field(), { target: { value: "3" } });

    expect(saveButton()).toBeDisabled();
  });

  it.each(["", "0", "21", "2.5", "x5", "abc"])("a typed %j is refused in words and cannot be saved", async (text) => {
    const { patches } = setupPage(strategy());
    await ready();

    fireEvent.change(field(), { target: { value: text } });

    expect(field()).toHaveAttribute("aria-invalid", "true");
    expect(field()).toHaveAccessibleDescription("Enter a whole number from 1 to 20.");
    expect(saveButton()).toBeDisabled();
    fireEvent.click(saveButton());
    expect(patches()).toHaveLength(0);
  });

  it("an invalid text leaves the handle where it was", async () => {
    setupPage(strategy());
    await ready();
    fireEvent.change(field(), { target: { value: "9" } });

    fireEvent.change(field(), { target: { value: "99" } });

    expect(track().value).toBe("9");
    expect(track()).toHaveAttribute("aria-valuetext", "x9");
  });

  it("an ARCHIVED strategy is read-only", async () => {
    const { patches } = setupProp(strategy({ archived_at: "2026-10-01T00:00:00Z" }));

    expect(field()).toBeDisabled();
    expect(track()).toBeDisabled();
    expect(saveButton()).toBeDisabled();
    expect(patches()).toHaveLength(0);
  });

  it("a LEAVING subscription is read-only", () => {
    setupProp(strategy({ subscription: subscription(3, { status: "LEAVING", left_at: "2026-10-28T10:00:00Z" }) }));

    expect(field()).toBeDisabled();
    expect(track()).toBeDisabled();
    expect(saveButton()).toBeDisabled();
  });

  it("with no subscription it draws nothing", () => {
    const { view } = setupProp(strategy({ subscription: null }));

    expect(view.container).toBeEmptyDOMElement();
  });

  it.each([
    [422, { detail: "no" }, "The leverage must be a whole number from 1 to 20."],
    [
      409,
      { detail: { error: "SUBSCRIPTION_NOT_ACTIVE", message: "not active" } },
      "Your subscription to this strategy is no longer active, so its leverage can no longer be changed.",
    ],
    [404, { detail: "gone" }, "This strategy no longer exists."],
    [500, { detail: "boom" }, "The leverage was not saved. Try again."],
  ])("a refused save (%i) says why, in words of the panel", async (status, body, text) => {
    const { patches } = setupPage(strategy(), { patch: () => jsonResponse(body, status) });
    await ready();
    fireEvent.change(field(), { target: { value: "8" } });

    fireEvent.click(saveButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(patches()).toHaveLength(1);
    expect(saveButton()).toHaveAccessibleName("Save leverage");
  });

  it("the explanation is closed until its button opens it, and says the system sets it on the exchange", async () => {
    setupPage(strategy());
    await ready();
    expect(screen.queryByText(/sets this leverage on the exchange/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "About the leverage" }));

    expect(screen.getByText(/sets this leverage on the exchange before each opening/)).toBeVisible();
    expect(screen.getByText(/keeps the leverage it was opened with/)).toBeVisible();
  });

  it("reads in Spanish with the usted form", async () => {
    await i18n.changeLanguage("es");
    setupPage(strategy());

    expect(await screen.findByRole("textbox", { name: "Apalancamiento" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar apalancamiento" })).toBeDisabled();
    expect(screen.getByRole("slider", { name: "Apalancamiento" })).toHaveAttribute("aria-valuetext", "x3");
  });
});
