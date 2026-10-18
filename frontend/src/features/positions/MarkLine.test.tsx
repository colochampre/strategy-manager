import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrderLine, VenueLine } from "@/features/positions/MarkLine";
import type { ConfirmedDiscrepancy } from "@/shared/api/discrepancies";
import i18n from "@/shared/i18n";
import { confirmedBody, discrepancy, lock, openOrder, openPosition, renderAt, stubApi, unlock } from "@/test/harness";
import type { ConfirmedStub } from "@/test/harness";

/**
 * T17, the lines' half: ONE base and two variants (design addendum § H, "One component for the two lines"), the
 * parts in the order of examples 18, 19 and 25e, and the accessible names of the venue line.
 */

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const AS_OF = "2026-10-12T21:40:03Z";
const ALLOCATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const DISCREPANCY = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";

beforeEach(async () => {
  unlock();
  await act(() => i18n.changeLanguage("en"));
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

async function settle() {
  for (let turn = 0; turn < 3; turn += 1) await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
}

/**
 * The discrepancy the position's disagreement names, as the confirmed-discrepancies route spells it: the id is
 * the join, and the symbol is the TradingView spelling while the position's market is the venue's (R21).
 */
function confirmedItem(overrides: Partial<ConfirmedDiscrepancy> = {}): ConfirmedDiscrepancy {
  return discrepancy({ discrepancy_id: DISCREPANCY, symbol: "AAVEUSDT.P", ...overrides });
}

const BEING_BOOKED: ConfirmedStub = {
  kind: "ok",
  body: confirmedBody({ being_booked: [confirmedItem({ reason: null, kind: "ATTRIBUTABLE_FULL_CLOSE" })] }),
};

function liveBeingBooked() {
  return { being_booked: [confirmedItem({ reason: null, kind: "ATTRIBUTABLE_FULL_CLOSE" })] };
}

function needsOwner(overrides: Partial<ConfirmedDiscrepancy> = {}): ConfirmedStub {
  return { kind: "ok", body: confirmedBody({ needs_owner: [confirmedItem(overrides)] }) };
}

function disagreeing(overrides: Parameters<typeof openPosition>[0] = {}) {
  return openPosition({
    allocation_id: ALLOCATION,
    markets: ["AAVEUSDT"],
    base_currency: "AAVE",
    venue_disagreement: {
      discrepancy_id: DISCREPANCY,
      venue_net_base: "0",
      ledger_net_base: "0.82000000",
      allocation_count: 1,
      last_observed_at: "2026-10-12T21:39:12Z",
    },
    ...overrides,
  });
}

/** Mounts a venue line over an answer to the confirmed discrepancies, and waits until it has been read. */
async function mountVenue(position = disagreeing(), confirmed: ConfirmedStub = BEING_BOOKED) {
  const api = stubApi(HEALTH, [], undefined, {}, undefined, {}, undefined, undefined, confirmed);
  const view = renderAt(<VenueLine position={position} asOf={AS_OF} />);
  await settle();
  return Object.assign(view, { api });
}

function mountOrder(overrides: Parameters<typeof openOrder>[0] = {}) {
  stubApi(HEALTH);
  const view = renderAt(<OrderLine order={openOrder(overrides)} asOf={AS_OF} />);
  return view.container.firstElementChild as HTMLElement;
}

/** The venue line, asserted to exist before it is returned, so that its absence is a failed assertion. */
function venueLine(name: string): HTMLElement {
  expect(screen.queryByRole("group", { name })).toBeInTheDocument();
  return screen.getByRole("group", { name });
}

/** The link of the venue line, asserted to exist (after the proposals are read) before it is returned. */
async function venueLink(name: string): Promise<HTMLElement> {
  await waitFor(() => expect(screen.queryByRole("link", { name })).toBeInTheDocument());
  return screen.getByRole("link", { name });
}

const BORDER_STYLE_AND_COLOUR = /^border-(dashed|solid|gain|loss|decision|rule-strong)$/;

function sharedClasses(element: Element): string[] {
  return [...element.classList].filter((name) => !BORDER_STYLE_AND_COLOUR.test(name)).sort();
}

describe("one base, two variants", () => {
  it("renders the same element with the same class list but for the border's style and colour", async () => {
    const order = mountOrder({ origin: "live" });
    const view = await mountVenue();

    const venue = venueLine("Venue disagrees, AAVEUSDT");
    expect(view.container).toContainElement(venue);
    expect(venue.tagName).toBe(order.tagName);
    expect(sharedClasses(venue)).toEqual(sharedClasses(order));
    expect(sharedClasses(venue)).toEqual(
      expect.arrayContaining(["border", "bg-transparent", "font-mono", "text-xs", "text-ink", "text-left", "w-full", "flex-wrap"]),
    );
  });

  it("draws the order line dashed in the origin's colour and the venue line solid red", async () => {
    const live = mountOrder({ origin: "live" });
    expect(live).toHaveClass("border-dashed", "border-gain");
    expect(live).not.toHaveClass("border-loss");

    await mountVenue();
    const venue = venueLine("Venue disagrees, AAVEUSDT");
    expect(venue).toHaveClass("border-loss");
    expect(venue).not.toHaveClass("border-dashed");
  });

  it.each([
    ["rehearsal", "border-decision"],
    ["live", "border-gain"],
    ["unknown", "border-rule-strong"],
  ] as const)("takes the %s order's border colour from the origin table: %s", (origin, border) => {
    expect(mountOrder({ origin })).toHaveClass("border-dashed", border);
  });
});

describe("the order line (example 19)", () => {
  it("reads pair, order in flight, closing, the origin and when it was sent, letter for letter", () => {
    const line = mountOrder({ market: "SFPUSDT", action: "CLOSE", origin: "rehearsal", submitted_at: "2026-10-12T21:12:00Z" });
    expect(line).toHaveTextContent("SFPUSDT · order in flight · closing · Dry run · sent 21:12 UTC");
  });

  it("reads 'opening' for an opening order and the live origin", () => {
    const line = mountOrder({ market: "AAVEUSDT", action: "OPEN", origin: "live", submitted_at: "2026-10-12T21:36:00Z" });
    expect(line).toHaveTextContent("AAVEUSDT · order in flight · opening · Live · sent 21:36 UTC");
  });

  it("writes 'sent' with its date when the instant is of the day before the answer's (T18)", () => {
    const line = mountOrder({ action: "OPEN", origin: "live", submitted_at: "2026-10-11T21:12:00Z" });
    expect(line.textContent).toBe("SOLUSDT · order in flight · opening · Live · sent 10/11/2026 21:12 UTC");
  });

  it("writes the date of a 'sent' of another day in the panel's language (T18)", async () => {
    await act(() => i18n.changeLanguage("es"));
    const line = mountOrder({ action: "CLOSE", origin: "live", submitted_at: "2026-10-11T21:12:00Z" });
    expect(line.textContent).toBe("SOLUSDT · orden en curso · cierre · En vivo · enviada 11/10/2026 21:12 UTC");
  });

  it("leaves 'opening' or 'closing' out, with its separator, when the action is null", () => {
    const line = mountOrder({ action: null, origin: "live", submitted_at: "2026-10-12T21:12:00Z" });
    expect(line.textContent).toBe("SOLUSDT · order in flight · Live · sent 21:12 UTC");
  });

  it("leaves 'sent' out, with its separator, when the instant is null", () => {
    const line = mountOrder({ action: "OPEN", origin: "live", submitted_at: null });
    expect(line.textContent).toBe("SOLUSDT · order in flight · opening · Live");
  });

  it("is only pair, order in flight and origin for an undecorated order", () => {
    const line = mountOrder({ action: null, submitted_at: null, origin: "unknown" });
    expect(line.textContent).toBe("SOLUSDT · order in flight · origin unknown");
  });

  it("writes the origin's word in the origin's token and the separators in the faint ink", () => {
    const line = mountOrder({ origin: "rehearsal" });
    expect(line.querySelector(".text-decision")).toHaveTextContent("Dry run");
    const separators = [...line.querySelectorAll(".text-ink-3")];
    expect(separators.length).toBeGreaterThan(0);
    for (const separator of separators) expect(separator.textContent?.trim()).toBe("·");
  });
});

describe("the venue line (examples 18 and 25e)", () => {
  it("reads pair, venue disagrees, both nets with the base currency, last compared, the words and the link", async () => {
    await mountVenue();
    const line = venueLine("Venue disagrees, AAVEUSDT");

    await venueLink("See the discrepancy, AAVEUSDT");
    expect(line.textContent).toBe(
      "AAVEUSDT · venue disagrees · exchange 0 AAVE, ledger 0.82 AAVE · last compared 21:39:12 UTC · being booked automatically · See the discrepancy",
    );
    expect(line.querySelector(".text-loss")).toHaveTextContent("venue disagrees");
  });

  it("leaves the base currency out of the nets when the position has none", async () => {
    await mountVenue(disagreeing({ base_currency: null }));
    const line = venueLine("Venue disagrees, AAVEUSDT");

    expect(line).toHaveTextContent("exchange 0, ledger 0.82 · last compared");
  });

  it("says that the difference is shared only above one position, before the link", async () => {
    const base = disagreeing();
    const shared = disagreeing({
      venue_disagreement: { ...base.venue_disagreement!, allocation_count: 2, venue_net_base: "90", ledger_net_base: "150" },
    });
    await mountVenue(shared);
    const line = venueLine("Venue disagrees, AAVEUSDT");

    await venueLink("See the discrepancy, AAVEUSDT");
    expect(line.textContent).toBe(
      "AAVEUSDT · venue disagrees · exchange 90 AAVE, ledger 150 AAVE · last compared 21:39:12 UTC · shared by 2 positions on this pair · being booked automatically · See the discrepancy",
    );
  });

  it("leaves the shared part out, with its separator, for a count of one", async () => {
    await mountVenue();
    const line = venueLine("Venue disagrees, AAVEUSDT");

    await venueLink("See the discrepancy, AAVEUSDT");
    expect(line.textContent).not.toContain("shared by");
    expect(line.textContent).not.toContain(" ·  · ");
  });

  it("is a group named for the pair, and its link leads to the item's hash on the discrepancies page", async () => {
    await mountVenue();

    const link = await venueLink("See the discrepancy, AAVEUSDT");
    expect(link).toHaveAttribute("href", `/discrepancies#discrepancy-${DISCREPANCY}`);
    expect(link).toHaveTextContent("See the discrepancy");
    expect(venueLine("Venue disagrees, AAVEUSDT")).toContainElement(link);
  });

  it("reads the same line in Spanish, with the fixed Spanish words", async () => {
    await act(() => i18n.changeLanguage("es"));
    await mountVenue();
    const line = venueLine("El exchange no coincide, AAVEUSDT");

    await venueLink("Ver la discrepancia, AAVEUSDT");
    expect(line.textContent).toBe(
      "AAVEUSDT · el exchange no coincide · exchange 0 AAVE, libro mayor 0.82 AAVE · última comparación 21:39:12 UTC · se está registrando automáticamente · Ver la discrepancia",
    );
  });

  it("reads the shared part in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    const base = disagreeing();
    await mountVenue(disagreeing({ venue_disagreement: { ...base.venue_disagreement!, allocation_count: 2 } }));
    const line = venueLine("El exchange no coincide, AAVEUSDT");

    await venueLink("Ver la discrepancia, AAVEUSDT");
    expect(line).toHaveTextContent("compartida por 2 posiciones en este par");
  });
});

describe("the venue line reads the confirmed discrepancies (owner decision 66 Q8; example 14)", () => {
  it.each([
    ["NOT_BOOKED", { reason: "NOT_BOOKED" as const, kind: "ATTRIBUTABLE_FULL_CLOSE" as const }, "could not be booked automatically"],
    [
      "SEVERAL_ALLOCATIONS",
      { reason: "SEVERAL_ALLOCATIONS" as const, kind: "ATTRIBUTABLE_FULL_CLOSE" as const },
      "one booking cannot split it",
    ],
    [
      "AMBIGUOUS_PARTIAL_REDUCE",
      { reason: "NOT_BOOKABLE" as const, kind: "AMBIGUOUS_PARTIAL_REDUCE" as const },
      "which strategy it reduced cannot be told",
    ],
  ])("says the words of a %s discrepancy in needs_owner, stays red and links to the item", async (_name, overrides, words) => {
    await mountVenue(disagreeing(), needsOwner(overrides));
    const line = venueLine("Venue disagrees, AAVEUSDT");

    const link = await venueLink("See the discrepancy, AAVEUSDT");
    expect(line.textContent).toBe(
      `AAVEUSDT · venue disagrees · exchange 0 AAVE, ledger 0.82 AAVE · last compared 21:39:12 UTC · ${words} · See the discrepancy`,
    );
    expect(line).toHaveClass("border-loss");
    expect(link).toHaveAttribute("href", `/discrepancies#discrepancy-${DISCREPANCY}`);
  });

  it("says the words of the reasons in Spanish, as the prototype writes them", async () => {
    await act(() => i18n.changeLanguage("es"));
    await mountVenue(disagreeing(), needsOwner({ reason: "NOT_BOOKED" }));
    const line = venueLine("El exchange no coincide, AAVEUSDT");

    await venueLink("Ver la discrepancia, AAVEUSDT");
    expect(line).toHaveTextContent("no se pudo registrar automáticamente · Ver la discrepancia");
  });

  it("draws the link with no words for a needs_owner reason that has none of its own", async () => {
    await mountVenue(disagreeing(), needsOwner({ reason: "REASON_UNKNOWN", kind: "NO_MATCHING_ALLOCATION" }));
    const line = venueLine("Venue disagrees, AAVEUSDT");

    await venueLink("See the discrepancy, AAVEUSDT");
    expect(line.textContent).toBe(
      "AAVEUSDT · venue disagrees · exchange 0 AAVE, ledger 0.82 AAVE · last compared 21:39:12 UTC · See the discrepancy",
    );
  });

  it("joins by the discrepancy's id, not by the pair: another id with the same pair makes no claim", async () => {
    await mountVenue(disagreeing(), needsOwner({ discrepancy_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee" }));
    const line = venueLine("Venue disagrees, AAVEUSDT");

    expect(line.textContent).toBe(
      "AAVEUSDT · venue disagrees · exchange 0 AAVE, ledger 0.82 AAVE · last compared 21:39:12 UTC",
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("says it is being booked, and links, when the read is live (dry_run false)", async () => {
    await mountVenue(disagreeing(), { kind: "ok", body: confirmedBody({ ...liveBeingBooked(), dry_run: false }) });
    const line = venueLine("Venue disagrees, AAVEUSDT");

    await venueLink("See the discrepancy, AAVEUSDT");
    expect(line.textContent).toContain("being booked automatically");
  });

  it("does not promise automatic booking nor link under dry run, whatever CONFIRMED rows a live period left (cd.f10)", async () => {
    await mountVenue(disagreeing(), { kind: "ok", body: confirmedBody({ ...liveBeingBooked(), dry_run: true }) });
    const line = venueLine("Venue disagrees, AAVEUSDT");

    expect(line.textContent).toBe(
      "AAVEUSDT · venue disagrees · exchange 0 AAVE, ledger 0.82 AAVE · last compared 21:39:12 UTC",
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("names no reason and draws no link for a needs_owner item under dry run: the page it links to draws no list", async () => {
    await mountVenue(disagreeing(), {
      kind: "ok",
      body: confirmedBody({ needs_owner: [confirmedItem({ reason: "NOT_BOOKED" })], dry_run: true }),
    });
    const line = venueLine("Venue disagrees, AAVEUSDT");

    expect(line.textContent).toBe(
      "AAVEUSDT · venue disagrees · exchange 0 AAVE, ledger 0.82 AAVE · last compared 21:39:12 UTC",
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("makes no claim for a being_booked id that belongs to ANOTHER position of the same symbol", async () => {
    const otherPositionsId = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
    const otherBeingBooked: ConfirmedStub = {
      kind: "ok",
      body: confirmedBody({
        being_booked: [confirmedItem({ discrepancy_id: otherPositionsId, reason: null, kind: "ATTRIBUTABLE_FULL_CLOSE" })],
      }),
    };
    await mountVenue(disagreeing(), otherBeingBooked);
    const line = venueLine("Venue disagrees, AAVEUSDT");

    expect(line.textContent).toBe(
      "AAVEUSDT · venue disagrees · exchange 0 AAVE, ledger 0.82 AAVE · last compared 21:39:12 UTC",
    );
    expect(line).toHaveClass("border-loss");
    expect(line.textContent).not.toContain("being booked");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it.each([
    ["the query is loading", { kind: "pending" } as ConfirmedStub],
    ["the read failed", { kind: "status", status: 500, body: { detail: "down" } } as ConfirmedStub],
    ["the body is not the route's shape", { kind: "ok", body: [] } as ConfirmedStub],
    ["the id is in neither list", { kind: "ok", body: confirmedBody() } as ConfirmedStub],
  ])("makes no claim and draws no link while %s: the red line and its nets stay", async (_name, confirmed) => {
    await mountVenue(disagreeing(), confirmed);
    const line = venueLine("Venue disagrees, AAVEUSDT");

    expect(line.textContent).toBe(
      "AAVEUSDT · venue disagrees · exchange 0 AAVE, ledger 0.82 AAVE · last compared 21:39:12 UTC",
    );
    expect(line).toHaveClass("border-loss");
    expect(line.querySelector(".text-loss")).toHaveTextContent("venue disagrees");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("asks for the confirmed discrepancies once and for no booking proposal", async () => {
    const view = await mountVenue();

    const urls = view.api.mock.calls.map(([url]) => String(url));
    expect(urls.filter((url) => url.endsWith("/reconciliation/confirmed"))).toHaveLength(1);
    expect(urls.filter((url) => url.includes("bookings"))).toEqual([]);
  });

  it("asks for nothing when the position has no disagreement", async () => {
    const view = await mountVenue(openPosition({ markets: ["AAVEUSDT"] }));

    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    expect(view.api.mock.calls.map(([url]) => String(url)).filter((url) => url.includes("reconciliation"))).toEqual([]);
  });
});
