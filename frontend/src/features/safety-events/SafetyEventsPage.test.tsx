import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SafetyEventsPage } from "@/features/safety-events/SafetyEventsPage";
import i18n from "@/shared/i18n";
import { jsonResponse, lock, renderAt, stubApi, unlock } from "@/test/harness";

const BASE = {
  strategy_id: "s1",
  strategy_name: "Breakout",
  allocation_id: "a1",
  exchange: "bybit",
  venue: "usdt-m",
  symbol: "SOLUSDT",
  occurred_at: "2026-11-17T10:05:00+00:00",
};

function event(id: string, kind: string, detail: Record<string, string>, overrides: Record<string, unknown> = {}) {
  return { id, kind, detail, ...BASE, ...overrides };
}

function serve(answer: () => Promise<Response>) {
  stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) =>
    url.endsWith("/api/safety-events") ? answer() : undefined,
  );
}

function open() {
  renderAt(<SafetyEventsPage />, "/safety-events");
}

beforeEach(unlock);
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

describe("SafetyEventsPage", () => {
  it("is titled under its own heading", async () => {
    serve(() => Promise.resolve(jsonResponse({ events: [] })));
    open();
    expect(await screen.findByRole("heading", { level: 1, name: "Safety events" })).toBeInTheDocument();
  });

  it("says it is reading while the answer is pending", async () => {
    serve(() => new Promise<Response>(() => undefined));
    open();
    expect(await screen.findByText("Reading safety events…")).toBeInTheDocument();
  });

  it("says so, as an alert, when the answer cannot be read", async () => {
    serve(() => Promise.resolve(jsonResponse({ nope: true })));
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("The safety events could not be read.");
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("says nothing has happened when the list is empty", async () => {
    serve(() => Promise.resolve(jsonResponse({ events: [] })));
    open();
    expect(await screen.findByText("Nothing has needed the safety net yet.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it.each([
    ["STOP_FIRED", { quantity: "0.5", trigger_price: "140" }, "Stop fired", "The stop was triggered at 140 and closed 0.5."],
    [
      "STOP_FAILED_CLOSED",
      { quantity: "0.5", price: "139.5" },
      "Closed after a failed stop",
      "The stop could not be kept in place, so the position was closed: 0.5 at 139.5.",
    ],
    [
      "STRATEGY_STOPPED_CLOSED",
      { quantity: "0.5", price: "139.5" },
      "Closed after the strategy stopped",
      "The strategy stopped, so the position was closed: 0.5 at 139.5.",
    ],
    ["MANUAL_CLOSE", { quantity: "0.5", price: "139.5" }, "Closed by you", "You closed the position: 0.5 at 139.5."],
    [
      "OPENING_REFUSED_LEVERAGE_CAP",
      { requested_leverage: "10", max_leverage: "5", stop_loss_pct: "2" },
      "Opening refused: leverage cap",
      "The opening asked for 10x, above the 5x allowed with a 2% stop, so nothing was opened.",
    ],
  ])("draws a %s row with its translated kind and detail", async (kind, detail, label, sentence) => {
    serve(() => Promise.resolve(jsonResponse({ events: [event("e1", kind, detail)] })));
    open();
    const list = await screen.findByRole("list", { name: "Safety events, newest first" });
    const row = within(list).getByRole("listitem");
    expect(within(row).getByText(label)).toBeInTheDocument();
    expect(within(row).getByText(sentence)).toBeInTheDocument();
    expect(row).toHaveTextContent("Breakout");
    expect(row).toHaveTextContent("SOLUSDT");
    expect(row).toHaveTextContent("Bybit");
    expect(row).toHaveTextContent("Nov 17, 2026, 10:05");
  });

  it("keeps the order the server gave, one row per event", async () => {
    serve(() =>
      Promise.resolve(
        jsonResponse({
          events: [
            event("e1", "MANUAL_CLOSE", { quantity: "1", price: "2" }, { strategy_name: "First" }),
            event("e2", "MANUAL_CLOSE", { quantity: "1", price: "2" }, { strategy_name: "Second" }),
          ],
        }),
      ),
    );
    open();
    const rows = within(await screen.findByRole("list")).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("First");
    expect(rows[1]).toHaveTextContent("Second");
  });

  it("falls back to a neutral row for a kind it does not know, without crashing", async () => {
    serve(() => Promise.resolve(jsonResponse({ events: [event("e1", "SOMETHING_NEW", { x: "1" })] })));
    open();
    const row = within(await screen.findByRole("list")).getByRole("listitem");
    expect(within(row).getByText("Safety event")).toBeInTheDocument();
    expect(within(row).getByText("No details are available for this event.")).toBeInTheDocument();
    expect(row).toHaveTextContent("Breakout");
  });

  it("writes n/a for a detail key a known kind lacks, never undefined", async () => {
    serve(() => Promise.resolve(jsonResponse({ events: [event("e1", "STOP_FIRED", { quantity: "0.5" })] })));
    open();
    const row = within(await screen.findByRole("list")).getByRole("listitem");
    expect(row).toHaveTextContent("The stop was triggered at n/a and closed 0.5.");
    expect(row).not.toHaveTextContent("undefined");
  });

  it("writes a stored figure short, without the trailing zeros or a long average", async () => {
    serve(() =>
      Promise.resolve(
        jsonResponse({
          events: [event("e1", "MANUAL_CLOSE", { quantity: "2.000000000000000000", price: "142.1233333333333333333333333" })],
        }),
      ),
    );
    open();
    const row = within(await screen.findByRole("list")).getByRole("listitem");
    expect(row).toHaveTextContent("You closed the position: 2 at 142.12333.");
  });

  it("is written in Spanish when the panel is", async () => {
    await i18n.changeLanguage("es");
    serve(() =>
      Promise.resolve(jsonResponse({ events: [event("e1", "MANUAL_CLOSE", { quantity: "0.5", price: "139.5" })] })),
    );
    open();
    const row = within(await screen.findByRole("list")).getByRole("listitem");
    expect(within(row).getByText("Cerrada por usted")).toBeInTheDocument();
    expect(within(row).getByText("Usted cerró la posición: 0.5 a 139.5.")).toBeInTheDocument();
  });

  it("makes the list focusable so the keyboard can scroll it", async () => {
    serve(() => Promise.resolve(jsonResponse({ events: [event("e1", "MANUAL_CLOSE", { quantity: "1", price: "2" })] })));
    open();
    expect(await screen.findByRole("list")).toHaveAttribute("tabindex", "0");
  });
});
