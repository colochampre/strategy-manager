import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import { NewStrategyDialog } from "@/features/strategies/NewStrategyDialog";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { availablePairs, jsonResponse, lock, pool, renderAt, resetExchangeScope, stubApi, unlock } from "@/test/harness";
import type { AvailablePairsStub, ExtraRoute } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const POOLS = { kind: "ok", body: [pool("bybit", "usdt-m"), pool("binance", "usdt-m")] } as const;
/** Two pools of one exchange, so the dialog can change pool without changing exchange. */
const TWO_BYBIT_POOLS = { kind: "ok", body: [pool("bybit", "usdt-m"), pool("bybit", "inverse", "BTC")] } as const;
const GENERATED_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

type Locale = typeof en;

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

function openDialog(text: Locale = en) {
  fireEvent.click(screen.getByRole("button", { name: text.strategies.new.open }));
  return screen.getByRole("dialog", { name: text.strategies.new.title });
}

function selectPool(poolValue: string, text: Locale = en) {
  fireEvent.change(screen.getByLabelText(text.strategies.new.pool), { target: { value: poolValue } });
}

/** Name, pool and fill mode; the pairs are chosen separately, from the pool's list. */
function fill(name: string, poolValue = "usdt-m/USDT", fillMode = "SKIP", text: Locale = en) {
  fireEvent.change(screen.getByLabelText(text.strategies.new.name), { target: { value: name } });
  selectPool(poolValue, text);
  fireEvent.change(screen.getByLabelText(text.strategies.new.fillMode), { target: { value: fillMode } });
}

/**
 * Chooses each symbol the way an operator does: waits for the list, types the
 * symbol in TradingView's spelling (`stxusdt.p`; the list holds `STXUSDT`) and
 * ticks the option.
 */
async function choose(symbols: readonly string[], text: Locale = en) {
  const search = await screen.findByRole("searchbox", { name: text.strategies.pairs.search });
  await waitFor(() => expect(search).toBeEnabled());
  for (const symbol of symbols) {
    fireEvent.change(search, { target: { value: `${symbol.toLowerCase()}.p` } });
    fireEvent.click(await screen.findByRole("checkbox", { name: symbol }));
  }
}

/**
 * A refusal text of a locale (`strategies.pairs.errors.<key>`), with `{{symbols}}`
 * filled in. A missing key reads as a marker, so a test fails on its text and
 * never on a `TypeError`.
 */
function refusal(locale: Locale, key: "unknown" | "venueUnavailable" | "notServed", symbols = ""): string {
  const errors = (locale.strategies.pairs as { errors?: Record<string, string> }).errors;
  return (errors?.[key] ?? `<missing strategies.pairs.errors.${key}>`).replace("{{symbols}}", symbols);
}

function submitButton(text: Locale = en) {
  return screen.getByRole("button", { name: text.strategies.new.submit });
}

/** The URLs asked for a pool's available pairs. */
function pairsRequests(fetchMock: ReturnType<typeof stubApi>): string[] {
  return fetchMock.mock.calls.map(([url]) => String(url)).filter((url) => url.includes("/available-pairs"));
}

function listedAs(pairs: readonly string[], venue = "usdt-m", currency = "USDT"): AvailablePairsStub {
  return { kind: "ok", body: availablePairs("bybit", venue, currency, pairs) };
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

describe("the new-strategy dialog", () => {
  it("test_pairs_are_chosen_from_the_pools_available_pairs_and_no_free_text_field_exists", async () => {
    const api = creationApi(created);
    const fetchMock = stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    const dialog = openDialog();

    // No pool yet: nothing is offered, the group says so and no request has been made.
    const group = within(dialog).getByRole("group", { name: en.strategies.new.pairs });
    expect(within(group).getByText(en.strategies.pairs.choosePool)).toBeInTheDocument();
    expect(within(group).getByRole("searchbox", { name: en.strategies.pairs.search })).toBeDisabled();
    expect(within(group).queryAllByRole("checkbox")).toEqual([]);
    expect(dialog.querySelector("textarea")).toBeNull();
    expect(pairsRequests(fetchMock)).toEqual([]);

    selectPool("usdt-m/USDT");

    // The group is rebuilt for the chosen pool, so it is looked up again.
    const chosen = within(dialog).getByRole("group", { name: en.strategies.new.pairs });
    await within(chosen).findByRole("checkbox", { name: "STXUSDT" });
    expect(within(chosen).getAllByRole("checkbox").map((box) => box.closest("label")?.textContent)).toEqual([
      "AAVEUSDT",
      "SFPUSDT",
      "STXUSDT",
    ]);
    // Exactly one request, for the chosen pool; a symbol the venue does not list has no option.
    expect(pairsRequests(fetchMock)).toEqual([expect.stringMatching(/\/api\/pools\/bybit\/usdt-m\/USDT\/available-pairs$/)]);
    expect(within(chosen).queryByRole("checkbox", { name: "YPF" })).not.toBeInTheDocument();
    expect(dialog.querySelector("textarea")).toBeNull();
  });

  it("test_selected_pairs_are_submitted_in_market_key_form", async () => {
    const api = creationApi(created);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();

    fill("Delta");
    await choose(["STXUSDT", "AAVEUSDT"]);
    fireEvent.click(submitButton());

    await waitFor(() => expect(api.posted).toHaveLength(1));
    // Typed as `stxusdt.p` and `aaveusdt.p`; sent as the venue's `STXUSDT`, in the order chosen.
    expect(api.posted[0]?.body.allowed_pairs).toEqual(["STXUSDT", "AAVEUSDT"]);
  });

  it("test_changing_the_pool_clears_the_selection_and_reads_the_new_pools_pairs", async () => {
    const api = creationApi(created);
    const fetchMock = stubApi(HEALTH, [], TWO_BYBIT_POOLS, {}, api.route, {
      "bybit/inverse/BTC": listedAs(["BTCUSD", "ETHUSD"], "inverse", "BTC"),
    });
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();

    fill("Delta");
    await choose(["STXUSDT"]);
    const chips = screen.getByRole("list", { name: en.strategies.pairs.selected });
    expect(within(chips).getByText("STXUSDT")).toBeInTheDocument();

    selectPool("inverse/BTC");

    // The previous pool's choice is gone and the new pool's list is on screen.
    await screen.findByRole("checkbox", { name: "BTCUSD" });
    expect(screen.queryByRole("list", { name: en.strategies.pairs.selected })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "STXUSDT" })).not.toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: en.strategies.pairs.search })).toHaveValue("");
    expect(pairsRequests(fetchMock).at(-1)).toMatch(/\/api\/pools\/bybit\/inverse\/BTC\/available-pairs$/);

    // Going back does not bring the old choice back either.
    selectPool("usdt-m/USDT");
    expect(await screen.findByRole("checkbox", { name: "STXUSDT" })).not.toBeChecked();
    expect(screen.queryByRole("list", { name: en.strategies.pairs.selected })).not.toBeInTheDocument();

    selectPool("inverse/BTC");
    await choose(["BTCUSD"]);
    fireEvent.click(submitButton());

    await waitFor(() => expect(api.posted).toHaveLength(1));
    expect(api.posted[0]?.body).toMatchObject({
      venue: "inverse",
      settlement_currency: "BTC",
      allowed_pairs: ["BTCUSD"],
    });
  });

  it("test_submit_is_disabled_until_the_available_pairs_are_loaded", async () => {
    const api = creationApi(created);
    stubApi(HEALTH, [], POOLS, {}, api.route, { "bybit/usdt-m/USDT": { kind: "pending" } });
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();

    expect(submitButton()).toBeDisabled();
    fill("Delta");

    expect(await screen.findByText(en.strategies.pairs.loading)).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
    fireEvent.click(submitButton());
    expect(api.posted).toEqual([]);
  });

  it("test_a_load_failure_shows_retry_and_never_a_free_text_field", async () => {
    const api = creationApi(created);
    let reads = 0;
    // The first read and the query's one automatic retry fail; the operator's Retry succeeds.
    const flaky: ExtraRoute = (url, init) => {
      if (url.includes("/available-pairs") && ++reads <= 2) {
        return Promise.resolve(jsonResponse({ detail: { error: "PAIR_CATALOGUE_UNAVAILABLE", message: "down" } }, 502));
      }
      return api.route(url, init);
    };
    stubApi(HEALTH, [], POOLS, {}, flaky);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    const dialog = openDialog();

    fill("Delta");

    const group = within(dialog).getByRole("group", { name: en.strategies.new.pairs });
    expect(await within(group).findByText(en.strategies.pairs.loadFailed, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(dialog.querySelector("textarea")).toBeNull();
    expect(within(group).getByRole("searchbox", { name: en.strategies.pairs.search })).toBeDisabled();
    expect(within(group).queryAllByRole("checkbox")).toEqual([]);
    expect(submitButton()).toBeDisabled();

    fireEvent.click(within(group).getByRole("button", { name: en.strategies.pairs.retry }));

    expect(await within(group).findByRole("checkbox", { name: "STXUSDT" })).toBeInTheDocument();
    expect(within(group).queryByText(en.strategies.pairs.loadFailed)).not.toBeInTheDocument();
  });

  it("test_unknown_pairs_refusal_names_the_symbols", async () => {
    const api = creationApi(() =>
      jsonResponse(
        { detail: { error: "UNKNOWN_PAIRS", message: "Not listed: YPF, ZZZ", unknown: ["YPF", "ZZZ"] } },
        422,
      ),
    );
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();
    fill("Delta");
    await choose(["STXUSDT"]);

    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(refusal(en, "unknown", "YPF, ZZZ"));
    // Nothing is lost: the dialog stays open, filled, and can be corrected and sent again.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText(en.strategies.new.name)).toHaveValue("Delta");
    expect(within(screen.getByRole("list", { name: en.strategies.pairs.selected })).getByText("STXUSDT")).toBeInTheDocument();
    expect(submitButton()).toBeEnabled();
  });

  it("test_a_502_shows_the_pair_list_could_not_be_read_text_even_without_a_body", async () => {
    const api = creationApi(() => jsonResponse(undefined, 502));
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();
    fill("Delta");
    await choose(["STXUSDT"]);

    fireEvent.click(submitButton());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(refusal(en, "venueUnavailable"));
    expect(alert).not.toHaveTextContent(en.strategies.new.errors.generic);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("reads the catalogue-unavailable code before the status", async () => {
    const api = creationApi(() =>
      jsonResponse({ detail: { error: "PAIR_CATALOGUE_UNAVAILABLE", message: "down" } }, 500),
    );
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();
    fill("Delta");
    await choose(["STXUSDT"]);

    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(refusal(en, "venueUnavailable"));
  });

  it("test_pair_catalogue_not_served_shows_its_own_text", async () => {
    const api = creationApi(() =>
      jsonResponse({ detail: { error: "PAIR_CATALOGUE_NOT_SERVED", message: "no catalogue" } }, 422),
    );
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();
    fill("Delta");
    await choose(["STXUSDT"]);

    fireEvent.click(submitButton());

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(refusal(en, "notServed"));
    expect(alert).not.toHaveTextContent(en.strategies.new.errors.invalid);
  });

  it("says pairs cannot be chosen for a pool whose catalogue is not served, and cannot be submitted", async () => {
    const api = creationApi(created);
    stubApi(HEALTH, [], POOLS, {}, api.route, {
      "bybit/usdt-m/USDT": {
        kind: "status",
        status: 404,
        body: { detail: { error: "PAIR_CATALOGUE_NOT_SERVED", message: "no catalogue" } },
      },
    });
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    const dialog = openDialog();

    fill("Delta");

    expect(await within(dialog).findByText(refusal(en, "notServed"), {}, { timeout: 4000 })).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
    expect(dialog.querySelector("textarea")).toBeNull();
    expect(api.posted).toEqual([]);
  });

  it("test_id_generated_via_crypto_randomuuid", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => GENERATED_ID });
    const api = creationApi(created);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();

    fill("Delta");
    await choose(["STXUSDT"]);
    fireEvent.click(submitButton());

    await waitFor(() => expect(api.posted).toHaveLength(1));
    expect(api.posted[0]?.body).toEqual({
      id: GENERATED_ID,
      name: "Delta",
      exchange: "bybit",
      venue: "usdt-m",
      settlement_currency: "USDT",
      fill_mode: "SKIP",
      allocation_percent: "100",
      allowed_pairs: ["STXUSDT"],
    });
    expect(api.posted[0]?.url).toMatch(/\/api\/strategies$/);
  });

  it("test_submitting_with_zero_pairs_is_prevented", async () => {
    const api = creationApi(created);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();

    fill("Delta");
    // Ready, with nothing chosen: submit is available and says a pair is needed.
    await screen.findByRole("checkbox", { name: "STXUSDT" });
    await waitFor(() => expect(submitButton()).toBeEnabled());
    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(en.strategies.new.pairsRequired);
    expect(api.posted).toEqual([]);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("requires a name, a pool and a fill mode, and sends nothing without them", async () => {
    const api = creationApi(created);
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();

    // No pool: there is nothing to choose pairs from, and submit is not available.
    expect(submitButton()).toBeDisabled();

    // A pool and a pair, but no name and no behaviour.
    selectPool("usdt-m/USDT");
    await choose(["STXUSDT"]);
    fireEvent.click(submitButton());

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

    fill("Delta");
    await choose(["STXUSDT"]);
    fireEvent.click(submitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(en.strategies.new.errors.conflict);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("keeps the dialog open and says so when the pool is refused (422)", async () => {
    const api = creationApi(() => jsonResponse({ detail: "pool unavailable" }, 422));
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(en.strategies.empty);
    openDialog();

    fill("Delta");
    await choose(["STXUSDT"]);
    fireEvent.click(submitButton());

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

    fill("Delta");
    await choose(["STXUSDT"]);
    fireEvent.click(submitButton());

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
    fill("Delta");
    await choose(["STXUSDT"]);

    fireEvent.click(submitButton());
    await screen.findByRole("alert");
    fireEvent.click(submitButton());

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
      // The free-text field is gone, and so is its hint.
      expect("pairsHint" in dialog).toBe(false);
    }
  });

  it("test_new_texts_render_in_es", async () => {
    await act(() => i18n.changeLanguage("es"));
    const api = creationApi(() =>
      jsonResponse({ detail: { error: "UNKNOWN_PAIRS", message: "x", unknown: ["YPF"] } }, 422),
    );
    stubApi(HEALTH, [], POOLS, {}, api.route);
    renderAt(<AppRoutes />, "/strategies");
    await screen.findByText(es.strategies.empty);
    const dialog = openDialog(es as Locale);

    const group = within(dialog).getByRole("group", { name: es.strategies.new.pairs });
    expect(within(group).getByText(es.strategies.pairs.choosePool)).toBeInTheDocument();

    fill("Delta", "usdt-m/USDT", "SKIP", es as Locale);
    await choose(["STXUSDT"], es as Locale);
    fireEvent.click(submitButton(es as Locale));

    expect(await screen.findByRole("alert")).toHaveTextContent(refusal(es as Locale, "unknown", "YPF"));
    for (const key of ["unknown", "venueUnavailable", "notServed"] as const) {
      expect(refusal(es as Locale, key)).not.toMatch(/^<missing/);
      expect(refusal(es as Locale, key)).not.toBe(refusal(en, key));
    }
  });
});
