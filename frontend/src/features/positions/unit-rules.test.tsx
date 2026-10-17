import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OpenMarks } from "@/features/positions/OpenMarks";
import { OpenStateLine } from "@/features/positions/OpenStateLine";
import type { Strategy } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import {
  confirmedBody,
  discrepancy,
  jsonResponse,
  lock,
  openOrder,
  openPosition,
  openState,
  renderAt,
  stubApi,
  unlock,
} from "@/test/harness";
import type { ConfirmedStub } from "@/test/harness";

/**
 * The rules the Strategies page's marks and summary follow as ONE unit (op.2.28): the palette, red only with its
 * words, dashed only on an order, no dialog, no navigation but the rail, no request but the panel's own, and the
 * same page in Spanish. Each test passes against the finished unit; its mutation is in the task's note.
 */

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;

const ALPHA = "11111111-1111-4111-8111-111111111111";
const ARCHIVED = "33333333-3333-4333-8333-333333333333";
const A_LINKED = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const A_UNLINKED = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const D_LINKED = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const D_UNLINKED = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";

function strategy(): Strategy {
  return {
    id: ALPHA,
    name: "Alpha",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    allocation_percent: "100",
    enabled: true,
    archived_at: null,
    allowed_pairs: ["SOLUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
  };
}

function disagreement(discrepancyId: string) {
  return {
    discrepancy_id: discrepancyId,
    venue_net_base: "0",
    ledger_net_base: "0.82",
    allocation_count: 1,
    last_observed_at: "2026-10-12T21:39:12Z",
  };
}

/** Positions of every origin, orders of every origin, a venue mark whose discrepancy is being booked and one whose is in neither list. */
const STATE = openState(
  [
    openPosition({ allocation_id: A_LINKED, strategy_id: ALPHA, markets: ["AAVEUSDT"], origin: "live", venue_disagreement: disagreement(D_LINKED) }),
    openPosition({
      allocation_id: A_UNLINKED,
      strategy_id: ALPHA,
      markets: ["SFPUSDT"],
      side: "SHORT",
      origin: "rehearsal",
      venue_disagreement: disagreement(D_UNLINKED),
    }),
    openPosition({ strategy_id: ALPHA, markets: ["STXUSDT"], origin: "mixed" }),
    openPosition({ strategy_id: ARCHIVED, strategy_archived: true, strategy_name: "LINK", markets: ["LINKUSDT"] }),
  ],
  [
    openOrder({ strategy_id: ALPHA, market: "ETHUSDT", origin: "rehearsal" }),
    openOrder({ strategy_id: ALPHA, market: "SOLUSDT", origin: "live" }),
    openOrder({ strategy_id: ALPHA, market: "XRPUSDT", origin: "unknown" }),
  ],
);

/** One discrepancy being booked, which the first mark names (its symbol in the TradingView spelling, R21); the second names none. */
const CONFIRMED: ConfirmedStub = {
  kind: "ok",
  body: confirmedBody({
    being_booked: [discrepancy({ discrepancy_id: D_LINKED, symbol: "AAVEUSDT.P", reason: null })],
  }),
};

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.hash}`}</p>;
}

/** Mounts the summary, the marks and a probe of the location; `current` is the positions answer a test may break. */
async function mountUnit() {
  const current: { status: number; body: unknown } = { status: 200, body: STATE };
  const route = (url: string) =>
    url.endsWith("/positions/open") ? Promise.resolve(jsonResponse(current.body, current.status)) : undefined;
  const api = stubApi(HEALTH, [], undefined, {}, route, {}, undefined, undefined, CONFIRMED);
  const view = renderAt(
    <>
      <OpenStateLine exchange="bybit" visibleStrategyIds={new Set([ALPHA])} />
      <ul>
        <li>
          <OpenMarks strategy={strategy()} />
        </li>
      </ul>
      <Where />
    </>,
  );
  await waitFor(() => expect(view.container.querySelectorAll("[class*='border']").length).toBeGreaterThan(3));
  await waitFor(() => expect(screen.queryByRole("link")).toBeInTheDocument());
  return { api, current, view };
}

/** Breaks the next read and presses the refresh button, so the summary says since when. */
async function goStale(current: { status: number; body: unknown }, refresh: string) {
  current.status = 500;
  current.body = { detail: "down" };
  fireEvent.click(screen.getByRole("button", { name: refresh }));
  await waitFor(() => expect(document.body.textContent ?? "").toMatch(/21:40:03 UTC\./));
}

beforeEach(async () => {
  unlock();
  await act(() => i18n.changeLanguage("en"));
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

describe("the marks follow one rule (palette, red with its words, dashed for an order)", () => {
  it("uses palette tokens only: no hex, no var() in a class, no style attribute", async () => {
    const { current, view } = await mountUnit();
    await goStale(current, "Read again");

    const everything = [...view.container.querySelectorAll("*")];
    expect(everything.length).toBeGreaterThan(20);
    for (const element of everything) {
      expect(element.getAttribute("class") ?? "").not.toMatch(/#[0-9a-f]{3,8}|var\(/i);
      expect(element.hasAttribute("style")).toBe(false);
    }
  });

  it("draws red only beside its words, the stale sentence and the venue chip included", async () => {
    const { current, view } = await mountUnit();
    await goStale(current, "Read again");

    const red = [...view.container.querySelectorAll("*")].filter((element) =>
      /(^|\s)(text|border|bg)-loss(\s|$)/.test(element.getAttribute("class") ?? ""),
    );
    // The venue chip (twice), the mixed origin's word and the stale sentence.
    expect(red.length).toBeGreaterThanOrEqual(4);
    for (const element of red) expect((element.textContent ?? "").trim()).not.toBe("");
    expect(red.map((element) => element.textContent)).toContain("Could not be refreshed since 21:40:03 UTC.");
  });

  it("draws a dashed border on the three orders and on nothing else", async () => {
    const { view } = await mountUnit();

    const dashed = [...view.container.querySelectorAll(".border-dashed")];
    expect(dashed.map((element) => element.textContent)).toEqual([
      "ETHUSDT · order in flight · Dry run",
      "SOLUSDT · order in flight · Live",
      "XRPUSDT · order in flight · origin unknown",
    ]);
  });
});

describe("the accessible names of the unit", () => {
  it("names the list and the link, and draws the counts as a status and no alert", async () => {
    const { view } = await mountUnit();

    expect(screen.getByRole("list", { name: "Open positions of Alpha" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See the discrepancy, AAVEUSDT" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Open:");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(view.container.querySelectorAll("[aria-hidden='true']")).toHaveLength(0);
  });

  it("hides the loading ellipsis from assistive technology and names the wait by the translated text", async () => {
    stubApi(HEALTH, [], undefined, {}, undefined, {}, undefined, { kind: "pending" });
    const view = renderAt(<OpenMarks strategy={strategy()} />);
    await waitFor(() => expect(screen.queryByText("…")).toBeInTheDocument());

    expect(screen.getByText("…")).toHaveAttribute("aria-hidden", "true");
    const hidden = [...view.container.querySelectorAll("[aria-hidden='true']")];
    const heard = (view.container.textContent ?? "").replace(hidden.map((node) => node.textContent ?? "").join(""), "");
    expect(heard).toBe("Reading open positions…");
  });
});

describe("what a mark and a row never do", () => {
  it("opens no dialog and goes nowhere when a chip, a row or a line is clicked", async () => {
    const { api, view } = await mountUnit();
    const requestsBefore = api.mock.calls.length;

    const chips = [...view.container.querySelectorAll("li span[class*='border']")];
    expect(chips.length).toBeGreaterThanOrEqual(8);
    for (const target of [
      ...chips,
      screen.getByText(/^Being booked automatically\./),
      ...screen.getAllByRole("listitem"),
      screen.getByText(/^Not on this list:/),
    ]) {
      fireEvent.click(target);
    }

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(view.container.querySelector("dialog, [aria-modal='true']")).toBeNull();
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/);
    expect(api.mock.calls.length).toBe(requestsBefore);
  });

  it("leads, by its link, to the item on the discrepancies page and nowhere else", async () => {
    await mountUnit();

    const item = `/discrepancies#discrepancy-${D_LINKED}`;
    const hrefs = [...document.querySelectorAll("a")].map((anchor) => anchor.getAttribute("href"));
    expect(hrefs).toEqual([item]);

    fireEvent.click(screen.getByRole("link", { name: "See the discrepancy, AAVEUSDT" }));
    expect(screen.getByTestId("where")).toHaveTextContent(item);
  });

  it("asks only the panel's own API: the open positions and the confirmed discrepancies, and nothing of a venue", async () => {
    const { api } = await mountUnit();

    const urls = api.mock.calls.map(([url]) => String(url));
    const paths = new Set(urls.map((url) => new URL(url, "http://panel.test").pathname.replace(/^.*\/api/, "")));
    expect([...paths].sort()).toEqual(["/positions/open", "/reconciliation/confirmed"]);
    expect(api.unexpected).toEqual([]);
    for (const [, init] of api.mock.calls) expect((init?.method ?? "GET").toUpperCase()).toBe("GET");
  });
});

describe("the same unit in Spanish", () => {
  it("writes every text of the unit in Spanish and leaves none of the English", async () => {
    await act(() => i18n.changeLanguage("es"));
    const { current, view } = await mountUnit();
    await goStale(current, "Leer de nuevo");

    const text = view.container.textContent ?? "";
    for (const spanish of [
      "Abiertas:",
      "Órdenes en curso:",
      "Última lectura:",
      "Fuera de esta lista: LINK · archivada · LINKUSDT · En vivo.",
      "No se pudo actualizar desde las 21:40:03 UTC.",
      "Leer de nuevo",
      "Simulación",
      "En vivo",
      "Simulación y en vivo",
      "orden en curso",
      "origen desconocido",
      "El exchange no coincide",
      "Se está registrando automáticamente.",
      "Ver la discrepancia",
    ]) {
      expect(text).toContain(spanish);
    }
    for (const english of [
      "Open:",
      "Orders in flight",
      "Last read",
      "Not on this list",
      "archived",
      "figures not readable",
      "Read again",
      "Dry run",
      "Live",
      "order in flight",
      "origin unknown",
      "Venue disagrees",
      "Being booked automatically",
      "See the discrepancy",
      "Could not be refreshed",
    ]) {
      expect(text).not.toContain(english);
    }
    expect(screen.getByRole("list", { name: "Posiciones abiertas de Alpha" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver la discrepancia, AAVEUSDT" })).toBeInTheDocument();
  });
});
