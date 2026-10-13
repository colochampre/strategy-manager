import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OpenStateLine } from "@/features/positions/OpenStateLine";
import type { OpenState } from "@/shared/api/positions";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import { jsonResponse, lock, openOrder, openPosition, openState, renderAt, stubApi, unlock } from "@/test/harness";
import type { ExtraRoute, OpenPositionsStub } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;

const ALPHA = "11111111-1111-4111-8111-111111111111";
const BETA = "22222222-2222-4222-8222-222222222222";
const ARCHIVED = "33333333-3333-4333-8333-333333333333";

beforeEach(async () => {
  unlock();
  await act(() => i18n.changeLanguage("en"));
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

function positionsRequests(api: ReturnType<typeof stubApi>): number {
  return api.mock.calls.filter(([url]) => String(url).endsWith("/positions/open")).length;
}

/** Mounts the line over one stubbed answer; the strategies list is `visible`, or null while it loads. */
function mount(openPositions: OpenPositionsStub, visible: ReadonlySet<string> | null = new Set(), exchange = "bybit") {
  const api = stubApi(HEALTH, [], undefined, {}, undefined, {}, undefined, openPositions);
  const view = renderAt(<OpenStateLine exchange={exchange} visibleStrategyIds={visible} />);
  return { api, view };
}

function answering(state: OpenState): OpenPositionsStub {
  return { kind: "ok", body: state };
}

/** The text of each figure (label and value) of the summary, in order. */
function figures(): string[] {
  // The counts sit in the status region and the time beside it, outside: two lists, one visual line.
  return [...document.querySelectorAll("dl > div")].map((figure) => figure.textContent ?? "");
}

async function settled(api: ReturnType<typeof stubApi>) {
  await waitFor(() => expect(positionsRequests(api)).toBeGreaterThan(0));
  // Let the answer reach the component.
  await act(() => Promise.resolve());
  await act(() => Promise.resolve());
}

describe("a failed first read draws no figure at all", () => {
  it("draws the error sentence as an alert in the loss colour with Read again, and never Open: 0", async () => {
    const { api } = mount({ kind: "status", status: 500, body: { detail: "boom" } });

    await settled(api);
    await waitFor(() => expect(screen.queryByRole("alert")).toBeInTheDocument());

    expect(screen.queryByText(/Open:/)).not.toBeInTheDocument();
    expect(figures()).toEqual([]);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(en.positions.state.error);
    expect(alert.className).toContain("text-loss");
    const button = screen.getByRole("button", { name: en.positions.state.refresh });
    expect(button.className).toContain("min-h-11");
  });

  it("does the same for a body that is not the shape", async () => {
    const { api } = mount({ kind: "ok", body: { as_of: "2026-10-12T21:40:03Z", positions: "none", orders: [] } });
    await settled(api);
    await waitFor(() => expect(screen.queryByRole("alert")).toBeInTheDocument());
    expect(figures()).toEqual([]);
  });

  it("reads the first answer again when Read again is pressed", async () => {
    const { api } = mount({ kind: "status", status: 500, body: {} });
    await settled(api);
    await waitFor(() => expect(screen.queryByRole("button")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: en.positions.state.refresh }));

    await waitFor(() => expect(positionsRequests(api)).toBe(2));
  });
});

describe("while nothing has been read", () => {
  it("draws the loading text as a status in the faint ink, with no button and no figure", async () => {
    const { api } = mount({ kind: "pending" });
    await waitFor(() => expect(positionsRequests(api)).toBeGreaterThan(0));

    const status = screen.queryByRole("status");
    expect(status).toBeInTheDocument();
    expect(status).toHaveTextContent(en.positions.state.loading);
    expect(status?.className ?? "").toContain("text-ink-3");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(figures()).toEqual([]);
  });
});

describe("the three figures", () => {
  const STATE = openState(
    [openPosition({ strategy_id: ALPHA }), openPosition({ strategy_id: BETA })],
    [openOrder({ strategy_id: ALPHA })],
  );

  it("draws the labels, the counts and the time with seconds and UTC", async () => {
    const { api } = mount(answering(STATE), new Set([ALPHA, BETA]));
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));

    expect(figures()).toEqual(["Open:2", "Orders in flight:1", "Last read:21:40:03 UTC"]);
    expect(screen.getByRole("button", { name: "Read again" })).toBeInTheDocument();
  });

  it("draws zero only from a successful read that holds nothing", async () => {
    const { api } = mount(answering(openState()));
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));

    expect(figures()).toEqual(["Open:0", "Orders in flight:0", "Last read:21:40:03 UTC"]);
  });

  it("keeps the two counts in the status region and the time outside it", async () => {
    const { api } = mount(answering(STATE), new Set([ALPHA, BETA]));
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));

    const region = screen.getByRole("status");
    expect(region).toHaveTextContent("Open:2");
    expect(region).toHaveTextContent("Orders in flight:1");
    expect(region).not.toHaveTextContent("Last read");
    expect(region).not.toHaveTextContent("21:40:03");
    expect(screen.getByText("21:40:03 UTC")).toBeInTheDocument();
    expect(region.contains(screen.getByText("21:40:03 UTC"))).toBe(false);
  });

  it("names no exchange", async () => {
    const { api } = mount(answering(STATE), new Set([ALPHA, BETA]));
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));

    expect(document.body.textContent ?? "").not.toMatch(/bybit|binance/i);
  });

  it("is written in Spanish through the same keys", async () => {
    await act(() => i18n.changeLanguage("es"));
    const { api } = mount(answering(STATE), new Set([ALPHA, BETA]));
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));

    expect(figures()).toEqual(["Abiertas:2", "Órdenes en curso:1", "Última lectura:21:40:03 UTC"]);
    expect(screen.getByRole("button", { name: "Leer de nuevo" })).toBeInTheDocument();
  });

  it("asks the server again at once when Read again is pressed", async () => {
    const { api } = mount(answering(STATE), new Set([ALPHA, BETA]));
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));
    expect(positionsRequests(api)).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: "Read again" }));

    await waitFor(() => expect(positionsRequests(api)).toBe(2));
  });
});

/** A stub whose answer the test changes between two reads. */
function switchable(first: OpenState) {
  const current: { status: number; body: unknown } = { status: 200, body: first };
  const route: ExtraRoute = (url) =>
    url.endsWith("/positions/open") ? Promise.resolve(jsonResponse(current.body, current.status)) : undefined;
  const api = stubApi(HEALTH, [], undefined, {}, route);
  return { current, api };
}

describe("a failed refresh", () => {
  it.each([
    ["one position", openState([openPosition({ strategy_id: ALPHA })], [], "2026-10-12T21:38:12Z"), "Open:1"],
    ["nothing at all", openState([], [], "2026-10-12T21:38:12Z"), "Open:0"],
  ])("keeps the last figures and says since when in red, also with %s", async (_label, first, open) => {
    const { current, api } = switchable(first);
    renderAt(<OpenStateLine exchange="bybit" visibleStrategyIds={new Set([ALPHA])} />);
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));

    current.status = 500;
    current.body = { detail: "down" };
    fireEvent.click(screen.getByRole("button", { name: "Read again" }));

    await waitFor(() => expect(screen.queryByText(en.positions.state.stale.replace("{{time}}", "21:38:12"))).toBeInTheDocument());
    expect(figures()[0]).toBe(open);
    expect(figures()[2]).toBe("Last read:21:38:12 UTC");
    const sentence = screen.getByText("Could not be refreshed since 21:38:12 UTC.");
    expect(sentence.className).toContain("text-loss");
    const region = screen.getByRole("status");
    expect(region.lastElementChild).toBe(sentence);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("changes no text inside the status region when a refetch changes only as_of", async () => {
    const first = openState([openPosition({ strategy_id: ALPHA })], [], "2026-10-12T21:38:12Z");
    const { current, api } = switchable(first);
    renderAt(<OpenStateLine exchange="bybit" visibleStrategyIds={new Set([ALPHA])} />);
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));
    const before = screen.getByRole("status").textContent;
    expect(screen.queryByText("21:38:12 UTC")).toBeInTheDocument();

    current.body = { ...first, as_of: "2026-10-12T21:39:12Z" };
    fireEvent.click(screen.getByRole("button", { name: "Read again" }));

    await waitFor(() => expect(screen.queryByText("21:39:12 UTC")).toBeInTheDocument());
    expect(screen.getByRole("status").textContent).toBe(before);
  });
});

/** The nearest element holding both nodes. */
function commonAncestor(a: Element, b: Element): Element {
  let node: Element | null = a;
  while (node !== null && !node.contains(b)) node = node.parentElement;
  if (node === null) throw new Error("no common ancestor");
  return node;
}

function liveAncestor(node: Element): Element | null {
  return node.closest("[role='status'], [role='alert'], [aria-live]");
}

describe("the layout: the figures on one row, the lines under it (example 10)", () => {
  const HIDDEN = openState([openPosition({ strategy_id: ALPHA }), openPosition({ strategy_id: ARCHIVED, strategy_archived: true })]);

  it("holds the counts and Last read in one row that does not contain the Not on this list line", async () => {
    const { api } = mount(answering(HIDDEN), new Set([ALPHA]));
    await settled(api);
    await waitFor(() => expect(screen.queryByText(/^Not on this list:/)).toBeInTheDocument());

    const row = commonAncestor(screen.getByText("Open:"), screen.getByText("Last read:"));
    expect(row.contains(screen.getByText("Orders in flight:"))).toBe(true);
    expect(row.contains(screen.getByText(/^Not on this list:/))).toBe(false);
  });

  it("puts Last read before the Not on this list line in the document", async () => {
    const { api } = mount(answering(HIDDEN), new Set([ALPHA]));
    await settled(api);
    await waitFor(() => expect(screen.queryByText(/^Not on this list:/)).toBeInTheDocument());

    const lastRead = screen.getByText("Last read:");
    const line = screen.getByText(/^Not on this list:/);
    expect(lastRead.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps the time outside every live region and the lines inside one", async () => {
    const { api } = mount(answering(HIDDEN), new Set([ALPHA]));
    await settled(api);
    await waitFor(() => expect(screen.queryByText(/^Not on this list:/)).toBeInTheDocument());

    expect(liveAncestor(screen.getByText("21:40:03 UTC"))).toBeNull();
    expect(liveAncestor(screen.getByText("Last read:"))).toBeNull();
    expect(liveAncestor(screen.getByText("Open:"))).not.toBeNull();
    expect(liveAncestor(screen.getByText(/^Not on this list:/))).not.toBeNull();
  });

  it("draws the stale line after the row, in a live region, and the time still outside one", async () => {
    const first = openState([openPosition({ strategy_id: ALPHA })], [], "2026-10-12T21:38:12Z");
    const { current, api } = switchable(first);
    renderAt(<OpenStateLine exchange="bybit" visibleStrategyIds={new Set([ALPHA])} />);
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));
    current.status = 500;
    current.body = { detail: "down" };
    fireEvent.click(screen.getByRole("button", { name: "Read again" }));
    const stale = await screen.findByText("Could not be refreshed since 21:38:12 UTC.");

    const row = commonAncestor(screen.getByText("Open:"), screen.getByText("Last read:"));
    expect(row.contains(stale)).toBe(false);
    expect(screen.getByText("Last read:").compareDocumentPosition(stale) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(liveAncestor(stale)).not.toBeNull();
    expect(liveAncestor(screen.getByText("21:38:12 UTC", { selector: "dd" }))).toBeNull();
  });
});

describe("what the exchange holds and the list does not show", () => {
  const SFP = openOrder({ strategy_id: BETA, strategy_name: "SFP 4h - RSI Divergences", market: "SFPUSDT" });
  const STATE = openState(
    [
      openPosition({ strategy_id: ALPHA, strategy_name: "AAVE 4h - RSI Divergences", markets: ["AAVEUSDT"] }),
      openPosition({
        strategy_id: ARCHIVED,
        strategy_name: "LINK 4h - RSI Divergences",
        strategy_archived: true,
        markets: ["LINKUSDT"],
        origin: "rehearsal",
      }),
      openPosition({
        strategy_id: null,
        strategy_archived: null,
        strategy_name: "STX 4h - RSI Divergences",
        markets: ["XYZBTC"],
        origin: "live",
        figures_missing: "UNRESOLVED_SYMBOL",
        side: null,
        size: null,
      }),
    ],
    [SFP],
  );
  const VISIBLE = new Set([ALPHA, BETA]);

  it("names the archived strategy's and the unmatched position, letter for letter as example 10", async () => {
    const { api } = mount(answering(STATE), VISIBLE);
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));

    expect(figures().slice(0, 2)).toEqual(["Open:3", "Orders in flight:1"]);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Not on this list: LINK 4h - RSI Divergences · archived · LINKUSDT · Dry run; STX 4h - RSI Divergences · XYZBTC · Live · figures not readable.",
    );
  });

  it("counts what the exchange holds: the count equals the elements on rows plus the items named", async () => {
    const { api } = mount(answering(STATE), VISIBLE);
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));

    const onRows = [...STATE.positions, ...STATE.orders].filter(
      (element) => element.strategy_id !== null && VISIBLE.has(element.strategy_id),
    ).length;
    const line = screen.getByText(/^Not on this list:/).textContent ?? "";
    const named = line.replace(/^Not on this list: /, "").replace(/\.$/, "").split("; ").length;
    expect(onRows + named).toBe(3 + 1);
  });

  it("names a hidden order by the chip's own words, positions first and then orders", async () => {
    const hiddenOrder = openOrder({
      strategy_id: ARCHIVED,
      strategy_archived: true,
      strategy_name: "SFP 4h - RSI Divergences",
      market: "SFPUSDT",
    });
    const state = openState(
      [openPosition({ strategy_id: ARCHIVED, strategy_name: "LINK", strategy_archived: true, markets: ["LINKUSDT"], origin: "rehearsal" })],
      [hiddenOrder],
    );
    const { api } = mount(answering(state), VISIBLE);
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));

    expect(screen.getByText(/^Not on this list:/)).toHaveTextContent(
      "Not on this list: LINK · archived · LINKUSDT · Dry run; SFP 4h - RSI Divergences · archived · SFPUSDT · order in flight · Live.",
    );
  });

  it("joins the market keys of a position with several by ' / '", async () => {
    const state = openState([openPosition({ strategy_id: null, strategy_name: "Gamma", markets: ["STXUSDT", "STXUSDC"] })]);
    const { api } = mount(answering(state), VISIBLE);
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));

    expect(screen.getByText(/^Not on this list:/)).toHaveTextContent("Not on this list: Gamma · STXUSDT / STXUSDC · Live.");
  });

  it("names an order whose strategy_name is null by its own mark text with no name in front (N3)", async () => {
    const state = openState(
      [],
      [
        openOrder({ strategy_id: null, strategy_name: null, strategy_archived: null, market: "SFPUSDT", origin: "live" }),
        openOrder({ strategy_id: null, strategy_name: null, strategy_archived: null, market: "STXUSDT", origin: "unknown" }),
      ],
    );
    const { api } = mount(answering(state), VISIBLE);
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));

    expect(screen.getByText(/^Not on this list:/)).toHaveTextContent(
      "Not on this list: SFPUSDT · order in flight · Live; STXUSDT · order in flight · origin unknown.",
    );
  });

  it("writes the same items in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    const { api } = mount(answering(STATE), VISIBLE);
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));

    expect(screen.getByRole("status")).toHaveTextContent(
      "Fuera de esta lista: LINK 4h - RSI Divergences · archivada · LINKUSDT · Simulación; STX 4h - RSI Divergences · XYZBTC · En vivo · cifras no legibles.",
    );
  });

  it("draws no second line when every element is carried by a row", async () => {
    const state = openState([openPosition({ strategy_id: ALPHA })], [openOrder({ strategy_id: BETA })]);
    const { api } = mount(answering(state), VISIBLE);
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));

    expect(screen.queryByText(/Not on this list/)).not.toBeInTheDocument();
  });

  it("withholds the second line while the strategies list loads, and draws the figures all the same", async () => {
    const { api } = mount(answering(STATE), null);
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));

    expect(figures().slice(0, 2)).toEqual(["Open:3", "Orders in flight:1"]);
    expect(screen.queryByText(/Not on this list/)).not.toBeInTheDocument();
  });

  it("names every element when the strategies list failed (no row carries any)", async () => {
    const { api } = mount(answering(STATE), new Set());
    await settled(api);
    await waitFor(() => expect(figures()).toHaveLength(3));

    const line = screen.getByText(/^Not on this list:/);
    expect(line).toHaveTextContent("AAVE 4h - RSI Divergences · AAVEUSDT · Live");
    expect(line).toHaveTextContent("LINK 4h - RSI Divergences");
    expect(line).toHaveTextContent("STX 4h - RSI Divergences");
    expect(line).toHaveTextContent("SFP 4h - RSI Divergences · SFPUSDT · order in flight · Live");
  });
});
