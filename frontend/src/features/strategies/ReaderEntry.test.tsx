import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import {
  emptyPerformance,
  jsonResponse,
  pool,
  publicRecord,
  publicStrategy,
  renderAt,
  resetExchangeScope,
  setViewport,
  stubApi,
  subscriptionOf,
  unlock,
  unsyncedSharePreview,
} from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const TOKEN = "Zr8kQ2vN_x1yPq3sLm4tB5wC6dE7fG8hJ9kL0mN1oP2";
const CODE = "K7QM-2XRA";

interface Seen {
  method: string;
  path: string;
  query: Record<string, string>;
  body: Record<string, unknown> | undefined;
}

interface Answers {
  /** The page's answer, given what the request carried. */
  page?: (query: Record<string, string>) => Response;
  lookup?: Response;
  subscribe?: Response;
}

const refusal = (status: number, detail: unknown) => jsonResponse({ detail }, status);
const dead = (reason: string) => refusal(410, { error: "INVITE_CODE_NOT_LIVE", reason, message: "x" });
const tooMany = () => refusal(429, { error: "TOO_MANY_CODE_ATTEMPTS", message: "x" });

/** Every request the panel makes, with its query and body, answered by `answers` or by an open strategy. */
function serve(answers: Answers = {}) {
  const seen: Seen[] = [];
  stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [pool("bybit")] }, {}, (raw, init) => {
    const url = new URL(raw, "http://test");
    const method = init?.method ?? "GET";
    const query = Object.fromEntries(url.searchParams.entries());
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as Record<string, unknown>) : undefined;
    const path = url.pathname;
    if (path === "/api/public/invite-codes/lookup" || path.startsWith(`/api/public/strategies/${ID}`) || path === "/api/subscriptions" || path.includes("/share-preview")) {
      seen.push({ method, path, query, body });
    }
    if (path === "/api/public/invite-codes/lookup") {
      return Promise.resolve(answers.lookup ?? jsonResponse({ strategy_id: ID }));
    }
    if (path === "/api/public/strategies") return Promise.resolve(jsonResponse([]));
    if (path === `/api/public/strategies/${ID}`) {
      return Promise.resolve(answers.page?.(query) ?? jsonResponse(publicStrategy({ id: ID })));
    }
    if (path === `/api/public/strategies/${ID}/record`) return Promise.resolve(jsonResponse(publicRecord()));
    if (path.startsWith(`/api/performance/strategies/${ID}`)) {
      return Promise.resolve(jsonResponse({ ...emptyPerformance("bybit", "usdt-m", "USDT"), strategy_id: ID, by_pair: [] }));
    }
    if (path === "/api/subscriptions/held") return Promise.resolve(jsonResponse([]));
    if (path === "/api/subscriptions" && method === "POST") {
      return Promise.resolve(answers.subscribe ?? jsonResponse(subscriptionOf(ID, "10"), 201));
    }
    if (path === `/api/strategies/${ID}/share-preview`) return Promise.resolve(jsonResponse(unsyncedSharePreview(ID)));
    if (path === "/api/me") {
      return Promise.resolve(jsonResponse({ email: "b@example.com", is_admin: false, mode: "LIVE", dry_run_brake: false }));
    }
    return undefined;
  });
  return seen;
}

const reads = (seen: Seen[], path: string) => seen.filter((each) => each.method === "GET" && each.path === path);
const pageOf = `/api/public/strategies/${ID}`;

async function subscribeWithTenPercent() {
  const field = await screen.findByRole("textbox", { name: i18n.t("strategies.detail.share.label") });
  fireEvent.change(field, { target: { value: "10" } });
  fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.subscribe.submit") }));
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
  setViewport("wide");
});

afterEach(async () => {
  vi.unstubAllGlobals();
  await act(() => i18n.changeLanguage("en"));
});

describe("I have a code, on Explore", () => {
  const openForm = async () => {
    fireEvent.click(await screen.findByRole("button", { name: "I have a code" }));
    return screen.getByRole("textbox", { name: "Invitation code" });
  };

  it("is offered even when no strategy is public, and asks for the code only when pressed", async () => {
    serve();
    renderAt(<AppRoutes />, "/strategies/explore");

    expect(await screen.findByRole("button", { name: "I have a code" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Invitation code" })).toBeNull();
    expect(await screen.findByText(i18n.t("strategies.explore.empty"))).toBeInTheDocument();
  });

  it("looks the code up and opens the page of the strategy it names, carrying the code", async () => {
    const seen = serve();
    renderAt(<AppRoutes />, "/strategies/explore");

    fireEvent.change(await openForm(), { target: { value: `  ${CODE} ` } });
    fireEvent.click(screen.getByRole("button", { name: "Open" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Alpha" })).toBeInTheDocument();
    expect(seen.filter((each) => each.method === "POST" && each.path === "/api/public/invite-codes/lookup").map((each) => each.body)).toEqual([
      { code: CODE },
    ]);
    expect(reads(seen, pageOf).map((each) => each.query)).toEqual([{ code: CODE }]);
  });

  it("sends nothing for an empty code", async () => {
    const seen = serve();
    renderAt(<AppRoutes />, "/strategies/explore");

    await openForm();

    expect(screen.getByRole("button", { name: "Open" })).toBeDisabled();
    expect(seen.filter((each) => each.path === "/api/public/invite-codes/lookup")).toEqual([]);
  });

  it.each([
    [() => refusal(404, "no strategy opens to that code"), "No strategy opens to that code. Check it and try again."],
    [() => dead("EXPIRED"), "This invitation code has expired. Ask the author for a new one."],
    [() => dead("REVOKED"), "This invitation code was revoked. Ask the author for a new one."],
    [() => dead("SPENT"), "This invitation code was already used. Ask the author for a new one."],
    [tooMany, "Too many wrong codes in the last hour. Try again later."],
    [() => refusal(500, "boom"), "The code could not be checked. Try again."],
    [() => jsonResponse({ id: ID }), "The code could not be checked. Try again."],
    [() => jsonResponse({ strategy_id: "" }), "The code could not be checked. Try again."],
  ])("says in words why a code opened nothing (%#), and stays on Explore", async (answer, text) => {
    serve({ lookup: answer() });
    renderAt(<AppRoutes />, "/strategies/explore");

    fireEvent.change(await openForm(), { target: { value: CODE } });
    fireEvent.click(screen.getByRole("button", { name: "Open" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(screen.getByRole("textbox", { name: "Invitation code" })).toHaveValue(CODE);
    expect(screen.queryByRole("heading", { level: 1, name: "Alpha" })).toBeNull();
  });

  it("speaks Spanish with usted", async () => {
    await act(() => i18n.changeLanguage("es"));
    serve({ lookup: tooMany() });
    renderAt(<AppRoutes />, "/strategies/explore");

    fireEvent.click(await screen.findByRole("button", { name: "Tengo un código" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Código de invitación" }), { target: { value: CODE } });
    fireEvent.click(screen.getByRole("button", { name: "Abrir" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Demasiados códigos incorrectos en la última hora. Inténtelo más tarde.");
  });
});

describe("a strategy's page opened by a link or a code", () => {
  it.each([
    ["link", `?link=${TOKEN}`, { link: TOKEN }],
    ["code", `?code=${CODE}`, { code: CODE }],
  ])("reads the page, its record and the share preview with the %s it was opened with", async (_case, search, query) => {
    const seen = serve();
    renderAt(<AppRoutes />, `/strategies/explore/${ID}${search}`);

    expect(await screen.findByRole("heading", { level: 1, name: "Alpha" })).toBeInTheDocument();
    await waitFor(() => expect(reads(seen, `${pageOf}/record`)).not.toEqual([]));
    await waitFor(() => expect(reads(seen, `/api/strategies/${ID}/share-preview`)).not.toEqual([]));

    expect(reads(seen, pageOf).map((each) => each.query)).toEqual([query]);
    expect(reads(seen, `${pageOf}/record`).map((each) => each.query)).toEqual([query]);
    for (const preview of reads(seen, `/api/strategies/${ID}/share-preview`)) {
      expect(preview.query).toMatchObject(query);
    }
  });

  it.each(["", "?link=&code="])("reads a page opened with neither (%j) as before, with no query", async (search) => {
    const seen = serve();
    renderAt(<AppRoutes />, `/strategies/explore/${ID}${search}`);

    await screen.findByRole("heading", { level: 1, name: "Alpha" });

    expect(reads(seen, pageOf).map((each) => each.query)).toEqual([{}]);
  });

  it.each([
    ["link", `?link=${TOKEN}`, { link_token: TOKEN }],
    ["code", `?code=${CODE}`, { invite_code: CODE }],
  ])("subscribes with the %s it was opened with", async (_case, search, entry) => {
    const seen = serve();
    renderAt(<AppRoutes />, `/strategies/explore/${ID}${search}`);

    await subscribeWithTenPercent();

    await waitFor(() => expect(seen.filter((each) => each.method === "POST" && each.path === "/api/subscriptions")).toHaveLength(1));
    const [posted] = seen.filter((each) => each.method === "POST" && each.path === "/api/subscriptions");
    expect(posted?.body).toEqual({ strategy_id: ID, allocation_percent: "10", leverage: 1, ...entry });
  });

  it("subscribes with neither when the page was opened with neither", async () => {
    const seen = serve();
    renderAt(<AppRoutes />, `/strategies/explore/${ID}`);

    await subscribeWithTenPercent();

    await waitFor(() => expect(seen.filter((each) => each.method === "POST" && each.path === "/api/subscriptions")).toHaveLength(1));
    const [posted] = seen.filter((each) => each.method === "POST" && each.path === "/api/subscriptions");
    expect(posted?.body).toEqual({ strategy_id: ID, allocation_percent: "10", leverage: 1 });
  });

  it.each([
    [`?code=${CODE}`, () => refusal(404, "x"), "No strategy opens to that code. Check it and try again."],
    [`?link=${TOKEN}`, () => refusal(404, "x"), "This link no longer opens the strategy. Ask its author for the current one."],
    [`?code=${CODE}`, () => dead("EXPIRED"), "This invitation code has expired. Ask the author for a new one."],
    [`?code=${CODE}`, () => dead("REVOKED"), "This invitation code was revoked. Ask the author for a new one."],
    [`?code=${CODE}`, () => dead("SPENT"), "This invitation code was already used. Ask the author for a new one."],
    [`?code=${CODE}`, tooMany, "Too many wrong codes in the last hour. Try again later."],
  ])("says in words why %s opened nothing", async (search, answer, text) => {
    serve({ page: answer });
    renderAt(<AppRoutes />, `/strategies/explore/${ID}${search}`);

    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1, name: "Alpha" })).toBeNull();
    expect(screen.queryByText(i18n.t("strategies.public.notFound"))).toBeNull();
  });

  it("a code refused on a later read wins over the strategy read before it", async () => {
    let reads = 0;
    serve({
      page: () => {
        reads += 1;
        return reads === 1 ? jsonResponse(publicStrategy({ id: ID })) : dead("SPENT");
      },
    });
    renderAt(<AppRoutes />, `/strategies/explore/${ID}?code=${CODE}`);

    await subscribeWithTenPercent();

    expect(await screen.findByText("This invitation code was already used. Ask the author for a new one.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1, name: "Alpha" })).toBeNull();
  });

  it.each([
    [() => dead("SPENT"), "This invitation code was already used. Ask the author for a new one."],
    [tooMany, "Too many wrong codes in the last hour. Try again later."],
  ])("says in words why subscribing with the code was refused (%#)", async (answer, text) => {
    serve({ subscribe: answer() });
    renderAt(<AppRoutes />, `/strategies/explore/${ID}?code=${CODE}`);

    await subscribeWithTenPercent();

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });
});
