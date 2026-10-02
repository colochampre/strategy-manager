import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import { NewStrategyDialog } from "@/features/strategies/NewStrategyDialog";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { jsonResponse, lock, pool, renderAt, resetExchangeScope, stubApi, unlock } from "@/test/harness";
import type { ExtraRoute } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const POOLS = { kind: "ok", body: [pool("bybit", "usdt-m"), pool("binance", "usdt-m")] } as const;
const GENERATED_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

interface Posted {
  url: string;
  body: Record<string, unknown>;
}

/** Records every POST /strategies and answers `answer`; lists answer empty. */
function creationApi(answer: () => Response) {
  const posted: Posted[] = [];
  const route: ExtraRoute = (url, init) => {
    if (!/\/strategies(\?|$)/.test(url)) return undefined;
    if (init?.method === "POST") {
      posted.push({ url, body: JSON.parse(String(init.body)) as Record<string, unknown> });
      return Promise.resolve(answer());
    }
    return Promise.resolve(jsonResponse([]));
  };
  return { posted, route };
}

function created() {
  return jsonResponse({ id: GENERATED_ID }, 201);
}

function openDialog() {
  fireEvent.click(screen.getByRole("button", { name: en.strategies.new.open }));
  return screen.getByRole("dialog", { name: en.strategies.new.title });
}

function fill(name: string, pairs: string, poolValue = "usdt-m/USDT", fillMode = "SKIP") {
  fireEvent.change(screen.getByLabelText(en.strategies.new.name), { target: { value: name } });
  fireEvent.change(screen.getByLabelText(en.strategies.new.pool), { target: { value: poolValue } });
  fireEvent.change(screen.getByLabelText(en.strategies.new.fillMode), { target: { value: fillMode } });
  fireEvent.change(screen.getByLabelText(en.strategies.new.pairs), { target: { value: pairs } });
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

describe("the new-strategy dialog", () => {
  it("test_id_generated_via_crypto_randomuuid", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => GENERATED_ID });
    const api = creationApi(created);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();

    fill("Delta", "STXUSDT.P");
    fireEvent.click(screen.getByRole("button", { name: en.strategies.new.submit }));

    await waitFor(() => expect(api.posted).toHaveLength(1));
    expect(api.posted[0]?.body).toEqual({
      id: GENERATED_ID,
      name: "Delta",
      exchange: "bybit",
      venue: "usdt-m",
      settlement_currency: "USDT",
      fill_mode: "SKIP",
      allocation_percent: "100",
      allowed_pairs: ["STXUSDT.P"],
    });
    expect(api.posted[0]?.url).toMatch(/\/api\/strategies$/);
  });

  it("test_submitting_with_zero_pairs_is_prevented", async () => {
    const api = creationApi(created);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();

    fill("Delta", "  ,\n , ");
    fireEvent.click(screen.getByRole("button", { name: en.strategies.new.submit }));

    expect(await screen.findByRole("alert")).toHaveTextContent(en.strategies.new.pairsRequired);
    expect(api.posted).toEqual([]);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("splits pairs on commas and lines, trims them and drops duplicates", async () => {
    const api = creationApi(created);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();

    fill("Delta", " STXUSDT.P, AAVEUSDT.P\nSTXUSDT.P ");
    fireEvent.click(screen.getByRole("button", { name: en.strategies.new.submit }));

    await waitFor(() => expect(api.posted).toHaveLength(1));
    expect(api.posted[0]?.body.allowed_pairs).toEqual(["STXUSDT.P", "AAVEUSDT.P"]);
  });

  it("requires a name, a pool and a fill mode, and sends nothing without them", async () => {
    const api = creationApi(created);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();

    fireEvent.change(screen.getByLabelText(en.strategies.new.pairs), { target: { value: "STXUSDT.P" } });
    fireEvent.click(screen.getByRole("button", { name: en.strategies.new.submit }));

    expect(await screen.findByRole("alert")).toHaveTextContent(en.strategies.new.incomplete);
    expect(api.posted).toEqual([]);
  });

  it("offers only the selected exchange's pools", async () => {
    stubApi(HEALTH, [], POOLS, {}, creationApi(created).route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();

    const options = Array.from(screen.getByLabelText(en.strategies.new.pool).querySelectorAll("option")).map(
      (option) => option.textContent,
    );
    expect(options).toContain("bybit · usdt-m · USDT");
    expect(options).not.toContain("binance · usdt-m · USDT");
  });

  it("keeps the dialog open and says why when the name is taken (409)", async () => {
    const api = creationApi(() => jsonResponse({ detail: "a strategy named 'Delta' already exists" }, 409));
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();

    fill("Delta", "STXUSDT.P");
    fireEvent.click(screen.getByRole("button", { name: en.strategies.new.submit }));

    expect(await screen.findByRole("alert")).toHaveTextContent(en.strategies.new.errors.conflict);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("keeps the dialog open and says so when the pool is refused (422)", async () => {
    const api = creationApi(() => jsonResponse({ detail: "pool unavailable" }, 422));
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();

    fill("Delta", "STXUSDT.P");
    fireEvent.click(screen.getByRole("button", { name: en.strategies.new.submit }));

    expect(await screen.findByRole("alert")).toHaveTextContent(en.strategies.new.errors.invalid);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("closes and refreshes the list after a successful creation", async () => {
    const api = creationApi(created);
    const fetchMock = stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    const listCallsBefore = fetchMock.mock.calls.filter(
      ([url, init]) => /\/strategies(\?|$)/.test(String(url)) && init?.method === undefined,
    ).length;
    openDialog();

    fill("Delta", "STXUSDT.P");
    fireEvent.click(screen.getByRole("button", { name: en.strategies.new.submit }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([url, init]) => /\/strategies(\?|$)/.test(String(url)) && init?.method === undefined),
      ).toHaveLength(listCallsBefore + 1),
    );
  });

  it("reuses the one generated id when the operator retries after a failure", async () => {
    let calls = 0;
    const uuid = vi.fn(() => `bbbbbbbb-bbbb-4bbb-8bbb-${String(++calls).padStart(12, "0")}`);
    vi.stubGlobal("crypto", { randomUUID: uuid });
    let attempt = 0;
    const api = creationApi(() => (++attempt === 1 ? jsonResponse({ detail: "x" }, 500) : created()));
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();
    fill("Delta", "STXUSDT.P");

    fireEvent.click(screen.getByRole("button", { name: en.strategies.new.submit }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: en.strategies.new.submit }));

    await waitFor(() => expect(api.posted).toHaveLength(2));
    expect(api.posted[1]?.body.id).toBe(api.posted[0]?.body.id);
  });

  it("cancels without sending anything", async () => {
    const api = creationApi(created);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();

    fireEvent.click(screen.getByRole("button", { name: en.strategies.new.cancel }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.posted).toEqual([]);
  });

  it("says there is no pool to register on when the exchange has none enabled", () => {
    stubApi(HEALTH, [], POOLS, {}, creationApi(created).route);
    renderAt(<NewStrategyDialog exchange="bybit" pools={[]} onClose={() => undefined} />);

    expect(screen.getByText(en.strategies.new.noPools)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: en.strategies.new.submit })).toBeDisabled();
  });
});

describe("copy", () => {
  it("has the dialog's messages in English and Spanish", () => {
    for (const locale of [en, es]) {
      const dialog = locale.strategies.new;
      for (const key of [
        "open",
        "title",
        "name",
        "pool",
        "fillMode",
        "pairs",
        "pairsHint",
        "pairsRequired",
        "incomplete",
        "noPools",
        "submit",
        "submitting",
        "cancel",
      ] as const) {
        expect(dialog[key]).toBeTruthy();
      }
      expect(dialog.errors.conflict).toBeTruthy();
      expect(dialog.errors.invalid).toBeTruthy();
      expect(dialog.errors.generic).toBeTruthy();
      expect(dialog.fillModes.SKIP).toBeTruthy();
      expect(dialog.fillModes.PARTIAL).toBeTruthy();
    }
  });
});
