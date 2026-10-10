import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AllowedPairsEditor } from "@/features/strategies/AllowedPairsEditor";
import type { Strategy } from "@/shared/api/types";
import { useTokenStore } from "@/shared/auth/token-store";
import i18n from "@/shared/i18n";
import { availablePairs, jsonResponse, stubApi } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const POOL = "bybit/usdt-m/USDT";

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
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
    ...overrides,
  };
}

type Put = { pairs: string[] };

/** Stubs the available pairs of the pool and the PUT; the PUT answers `answer` and its bodies are collected. */
function setup(
  subject: Strategy,
  options: { listed?: string[] | "fail"; answer?: (body: Put) => Response } = {},
) {
  const puts: Put[] = [];
  const listed = options.listed ?? ["ETHUSDT", "SOLUSDT", "BTCUSDT"];
  const fetchMock = stubApi(
    { kind: "ok", body: { status: "ok", dry_run: true } },
    [],
    undefined,
    {},
    (url, init) => {
      if (!url.endsWith("/allowed-pairs") || init?.method !== "PUT") return undefined;
      const body = JSON.parse(String(init.body)) as Put;
      puts.push(body);
      return Promise.resolve(options.answer?.(body) ?? jsonResponse({ ...subject, allowed_pairs: body.pairs }));
    },
    {
      [POOL]:
        listed === "fail"
          ? { kind: "status", status: 502, body: { detail: { error: "PAIR_CATALOGUE_UNAVAILABLE", message: "down" } } }
          : { kind: "ok", body: availablePairs("bybit", "usdt-m", "USDT", listed) },
    },
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const ui = (current: Strategy) => (
    <QueryClientProvider client={client}>
      <AllowedPairsEditor strategy={current} />
    </QueryClientProvider>
  );
  const view = render(ui(subject));
  return { puts, fetchMock, rerender: (current: Strategy) => view.rerender(ui(current)) };
}

const saveButton = () => screen.getByRole("button", { name: i18n.t("strategies.detail.pairs.save") });
const remove = (symbol: string) => fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.pairs.remove", { symbol }) }));
/** The available-pairs query retries once after a second before it reports a failure. */
const loadFailed = () => screen.findByText(i18n.t("strategies.pairs.loadFailed"), {}, { timeout: 3000 });
/** The catalogue is listed only once the operator types: waits for the search field, types the symbol, ticks it. */
const add = async (symbol: string) => {
  const search = await screen.findByLabelText(i18n.t("strategies.pairs.search"));
  await waitFor(() => expect(search).toBeEnabled());
  fireEvent.change(search, { target: { value: symbol } });
  fireEvent.click(await screen.findByRole("checkbox", { name: symbol }));
};
const catalogueReady = () =>
  waitFor(() => expect(screen.getByLabelText(i18n.t("strategies.pairs.search"))).toBeEnabled());

beforeEach(() => {
  useTokenStore.setState({ token: "a-token" });
});
afterEach(() => {
  vi.unstubAllGlobals();
  useTokenStore.setState({ token: null });
});

describe("AllowedPairsEditor", () => {
  it("test_removing_last_pair_without_replacement_prevented", async () => {
    const { puts } = setup(strategy());
    await catalogueReady();

    remove("ETHUSDT");

    expect(saveButton()).toBeDisabled();
    expect(screen.getByText(i18n.t("strategies.detail.pairs.lastPair"))).toBeInTheDocument();
    fireEvent.click(saveButton());
    expect(puts).toEqual([]);
  });

  it("allows the save once a replacement is added after removing the last pair", async () => {
    const { puts } = setup(strategy());

    remove("ETHUSDT");
    await add("SOLUSDT");

    expect(saveButton()).toBeEnabled();
    expect(screen.queryByText(i18n.t("strategies.detail.pairs.lastPair"))).toBeNull();
    fireEvent.click(saveButton());
    await waitFor(() => expect(puts).toEqual([{ pairs: ["SOLUSDT"] }]));
  });

  it("test_adding_a_pair_submits_full_updated_set", async () => {
    const { puts } = setup(strategy());
    expect(saveButton()).toBeDisabled();

    await add("SOLUSDT");
    fireEvent.click(saveButton());

    await waitFor(() => expect(puts).toEqual([{ pairs: ["ETHUSDT", "SOLUSDT"] }]));
  });

  it("test_stored_pair_missing_from_the_catalogue_is_kept_and_marked_no_longer_listed", async () => {
    const { puts } = setup(strategy({ allowed_pairs: ["SFPUSDT"] }), { listed: ["SOLUSDT", "STXUSDT"] });

    await catalogueReady();
    const chips = screen.getByRole("list", { name: i18n.t("strategies.pairs.selected") });
    expect(chips).toHaveTextContent("SFPUSDT");
    expect(chips).toHaveTextContent(i18n.t("strategies.pairs.notListed"));
    expect(saveButton()).toBeDisabled();

    await add("STXUSDT");
    fireEvent.click(saveButton());

    await waitFor(() => expect(puts).toEqual([{ pairs: ["SFPUSDT", "STXUSDT"] }]));
  });

  it("test_a_removal_only_save_is_allowed_when_the_available_pairs_failed_to_load", async () => {
    const { puts } = setup(strategy({ allowed_pairs: ["ETHUSDT", "SOLUSDT"] }), { listed: "fail" });
    await loadFailed();

    remove("SOLUSDT");

    expect(saveButton()).toBeEnabled();
    fireEvent.click(saveButton());
    await waitFor(() => expect(puts).toEqual([{ pairs: ["ETHUSDT"] }]));
  });

  it("test_adding_is_blocked_while_the_available_pairs_failed_to_load", async () => {
    setup(strategy(), { listed: "fail" });
    await loadFailed();

    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(screen.getByLabelText(i18n.t("strategies.pairs.search"))).toBeDisabled();
    expect(saveButton()).toBeDisabled();
  });

  it("test_409_pairs_changed_shows_the_review_and_save_again_text", async () => {
    setup(strategy(), {
      answer: () => jsonResponse({ detail: { error: "PAIRS_CHANGED", message: "changed" } }, 409),
    });

    await add("SOLUSDT");
    fireEvent.click(saveButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.pairs.errors.changed"));
    expect(i18n.t("strategies.pairs.errors.changed")).toBe("The list changed while you were editing. Review it and save again.");
  });

  it("test_422_unknown_pairs_names_the_symbols", async () => {
    setup(strategy(), {
      answer: () => jsonResponse({ detail: { error: "UNKNOWN_PAIRS", message: "unknown", unknown: ["SOLUSDT", "XYZUSDT"] } }, 422),
    });

    await add("SOLUSDT");
    fireEvent.click(saveButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.pairs.errors.unknown", { symbols: "SOLUSDT, XYZUSDT" }));
  });

  it("says nothing was saved when the exchange's pair list could not be read, and any other refusal generically", async () => {
    setup(strategy(), {
      answer: () => jsonResponse({ detail: { error: "PAIR_CATALOGUE_UNAVAILABLE", message: "down" } }, 502),
    });
    await add("SOLUSDT");
    fireEvent.click(saveButton());
    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.pairs.errors.venueUnavailable"));
  });

  it("reports a refusal that carries no known code with the generic text", async () => {
    setup(strategy(), { answer: () => jsonResponse({ detail: "boom" }, 500) });
    await add("SOLUSDT");
    fireEvent.click(saveButton());
    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.detail.pairs.saveFailed"));
  });

  it("drops an edit made on a stored list that has since changed, and shows the stored list", async () => {
    const { rerender } = setup(strategy());
    await add("SOLUSDT");
    expect(screen.getByRole("button", { name: i18n.t("strategies.pairs.remove", { symbol: "SOLUSDT" }) })).toBeInTheDocument();

    rerender(strategy({ allowed_pairs: ["ETHUSDT", "BTCUSDT"] }));

    expect(screen.getByRole("button", { name: i18n.t("strategies.pairs.remove", { symbol: "BTCUSDT" }) })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: i18n.t("strategies.pairs.remove", { symbol: "SOLUSDT" }) })).toBeNull();
    expect(saveButton()).toBeDisabled();
  });

  it("is read-only for an archived strategy: chips cannot be removed and nothing can be saved", async () => {
    const { puts } = setup(strategy({ archived_at: "2026-09-01T00:00:00+00:00", allowed_pairs: ["ETHUSDT", "SOLUSDT"] }));
    await screen.findByRole("list", { name: i18n.t("strategies.pairs.selected") });

    expect(screen.getByRole("button", { name: i18n.t("strategies.pairs.remove", { symbol: "SOLUSDT" }) })).toBeDisabled();
    expect(saveButton()).toBeDisabled();
    expect(puts).toEqual([]);
  });
});

/** The live region beside Save, found by either of the button's two names. */
function savedRegion(): HTMLElement {
  const button = screen.getByRole("button", {
    name: new RegExp(`^(${i18n.t("strategies.detail.pairs.save")}|${i18n.t("strategies.detail.pairs.saving")})$`),
  });
  const region = button.parentElement?.querySelector<HTMLElement>('[role="status"]');
  if (region === null || region === undefined) throw new Error("no live region beside Save");
  return region;
}

const settle = () => act(() => new Promise<void>((resolve) => setTimeout(resolve, 30)));

/** Adds SOLUSDT, saves, and hands the page the saved list the way a successful re-read does. */
async function saveSolana(rerenderWith?: (current: Strategy) => void, puts?: unknown[]) {
  await add("SOLUSDT");
  fireEvent.click(saveButton());
  await waitFor(() => expect(puts).toEqual([{ pairs: ["ETHUSDT", "SOLUSDT"] }]));
  rerenderWith?.(strategy({ allowed_pairs: ["ETHUSDT", "SOLUSDT"] }));
}

describe("AllowedPairsEditor, 'Saved' for the allowed pairs", () => {
  it("the live region is in the document before any save, empty", async () => {
    setup(strategy());
    await catalogueReady();

    expect(savedRegion()).toBeEmptyDOMElement();
    expect(savedRegion()).toHaveAttribute("aria-live", "polite");
  });

  it("Saved shows when the PUT answers 200 and the list on screen is the saved one", async () => {
    const { puts, rerender } = setup(strategy());

    await saveSolana(rerender, puts);

    await waitFor(() => expect(savedRegion()).toHaveTextContent("Saved"));
    expect(saveButton()).toBeDisabled();
  });

  it("Saved goes at the next pair added or removed", async () => {
    const { puts, rerender } = setup(strategy());
    await saveSolana(rerender, puts);
    await waitFor(() => expect(savedRegion()).toHaveTextContent("Saved"));

    remove("SOLUSDT");
    expect(savedRegion()).toBeEmptyDOMElement();
  });

  it("Saved goes when a pair is added", async () => {
    const { puts, rerender } = setup(strategy());
    await saveSolana(rerender, puts);
    await waitFor(() => expect(savedRegion()).toHaveTextContent("Saved"));

    await add("BTCUSDT");
    expect(savedRegion()).toBeEmptyDOMElement();
  });

  it("typing in the search box changes no pair and leaves Saved", async () => {
    const { puts, rerender } = setup(strategy());
    await saveSolana(rerender, puts);
    await waitFor(() => expect(savedRegion()).toHaveTextContent("Saved"));

    fireEvent.change(screen.getByLabelText(i18n.t("strategies.pairs.search")), { target: { value: "BTC" } });

    expect(savedRegion()).toHaveTextContent("Saved");
  });

  it.each([
    ["a 409", () => jsonResponse({ detail: { error: "PAIRS_CHANGED", message: "changed" } }, 409)],
    ["a 422", () => jsonResponse({ detail: { error: "UNKNOWN_PAIRS", message: "unknown", unknown: ["SOLUSDT"] } }, 422)],
  ])("no Saved after %s", async (_name, answer) => {
    setup(strategy(), { answer });

    await add("SOLUSDT");
    fireEvent.click(saveButton());

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(savedRegion()).toBeEmptyDOMElement();
  });

  it("if the re-read after a 200 fails, so the list on screen is the old one, Saved is not shown", async () => {
    const { puts } = setup(strategy());

    await saveSolana(undefined, puts);
    await settle();

    // The page never received the saved list: the stored list is still the old one.
    expect(savedRegion()).toBeEmptyDOMElement();
  });

  it("a 200 whose body is not a strategy does not show Saved, even when the page then holds the saved list", async () => {
    const { puts, rerender } = setup(strategy(), { answer: () => jsonResponse({ ok: true }) });

    await saveSolana(rerender, puts);
    await settle();

    expect(savedRegion()).toBeEmptyDOMElement();
  });

  it("a refusal and Saved are never on screen together: a new save clears the earlier Saved first", async () => {
    let calls = 0;
    const { puts, rerender } = setup(strategy(), {
      answer: (body) =>
        ++calls === 1
          ? jsonResponse({ ...strategy(), allowed_pairs: body.pairs })
          : jsonResponse({ detail: { error: "PAIRS_CHANGED", message: "changed" } }, 409),
    });
    // The first save is answered, but the page never receives the saved list, so Save stays enabled.
    await saveSolana(undefined, puts);
    await waitFor(() => expect(saveButton()).toBeEnabled());

    fireEvent.click(saveButton());
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    rerender(strategy({ allowed_pairs: ["ETHUSDT", "SOLUSDT"] }));

    expect(savedRegion()).toBeEmptyDOMElement();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("Saved stays ten minutes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { puts, rerender } = setup(strategy());
      await saveSolana(rerender, puts);
      await waitFor(() => expect(savedRegion()).toHaveTextContent("Saved"));

      await act(async () => {
        vi.advanceTimersByTime(600_000);
      });

      expect(savedRegion()).toHaveTextContent("Saved");
    } finally {
      vi.useRealTimers();
    }
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

const hintText = () => screen.getByText(i18n.t("strategies.detail.pairs.hint"));
/** Whether `before` comes before `after` in the document, which is the order on screen. */
const precedes = (before: Element, after: Element) =>
  (before.compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;

describe("AllowedPairsEditor, Save sits to the right of the note (12f.10.30c)", () => {
  it("Save and the note share one horizontal row, aligned to the top, that does not wrap", async () => {
    setup(strategy());
    await catalogueReady();

    const row = sharedRow(saveButton(), hintText());

    expect(classesOf(row)).toEqual(expect.arrayContaining(["flex", "items-start"]));
    expect(classesOf(row)).not.toContain("flex-col");
    expect(classesOf(row)).not.toContain("flex-wrap");
    // The row is the note and the button block, not the whole control.
    expect(row.contains(screen.getByLabelText(i18n.t("strategies.pairs.search")))).toBe(false);
    expect(row.children).toHaveLength(2);
  });

  it("the left block is the note and takes the room that is left", async () => {
    setup(strategy());
    await catalogueReady();
    const row = sharedRow(saveButton(), hintText());

    const text = childHolding(row, hintText());

    expect(text.contains(saveButton())).toBe(false);
    expect(classesOf(text)).toEqual(expect.arrayContaining(["min-w-0", "flex-1"]));
    expect(row.firstElementChild).toBe(text);
  });

  it("the right block is Saved and then Save, keeps its size and is aligned to the top", async () => {
    setup(strategy());
    await catalogueReady();
    const row = sharedRow(saveButton(), hintText());

    const actions = childHolding(row, saveButton());

    expect(actions).not.toBe(childHolding(row, hintText()));
    expect(classesOf(actions)).toEqual(expect.arrayContaining(["flex", "items-start", "shrink-0"]));
    expect(classesOf(actions)).not.toContain("flex-wrap");
    expect(precedes(savedRegion(), saveButton())).toBe(true);
    expect(actions.contains(savedRegion())).toBe(true);
    expect(saveButton().className).toContain("min-h-11");
  });

  it("the reading order is the selector, the note, Saved, then Save", async () => {
    setup(strategy());
    await catalogueReady();

    const search = screen.getByLabelText(i18n.t("strategies.pairs.search"));
    expect(precedes(search, hintText())).toBe(true);
    expect(precedes(hintText(), savedRegion())).toBe(true);
    expect(precedes(savedRegion(), saveButton())).toBe(true);
  });

  it("the warning about the last pair is outside the row", async () => {
    setup(strategy());
    await catalogueReady();
    const row = sharedRow(saveButton(), hintText());

    remove("ETHUSDT");

    const warning = screen.getByText(i18n.t("strategies.detail.pairs.lastPair"));
    expect(row.contains(warning)).toBe(false);
    expect(row.parentElement?.contains(warning)).toBe(true);
  });

  it("a failed save is an alert outside the row", async () => {
    setup(strategy(), { answer: () => jsonResponse({ detail: "boom" }, 500) });
    await catalogueReady();
    const row = sharedRow(saveButton(), hintText());
    await add("SOLUSDT");

    fireEvent.click(saveButton());

    const alert = await screen.findByRole("alert");
    expect(row.contains(alert)).toBe(false);
    expect(row.parentElement?.contains(alert)).toBe(true);
  });
});
