import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrderLine, VenueLine } from "@/features/positions/MarkLine";
import i18n from "@/shared/i18n";
import { lock, openOrder, openPosition, renderAt, stubApi, unlock } from "@/test/harness";

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

function proposal(overrides: Record<string, unknown> = {}) {
  return {
    id: "pppppppp-pppp-4ppp-8ppp-pppppppppppp",
    discrepancy_id: DISCREPANCY,
    allocation_id: ALLOCATION,
    state: "PENDING",
    ...overrides,
  };
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

/** Mounts a venue line over an answer to the pending bookings, and waits until it has been read. */
async function mountVenue(position = disagreeing(), bookings: unknown[] = [proposal()]) {
  stubApi(HEALTH, bookings);
  const view = renderAt(<VenueLine position={position} asOf={AS_OF} />);
  await settle();
  return view;
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
  it("reads pair, venue disagrees, both nets with the base currency, last compared and the link", async () => {
    await mountVenue();
    const line = venueLine("Venue disagrees, AAVEUSDT");

    await venueLink("See the pending decision, AAVEUSDT");
    expect(line.textContent).toBe(
      "AAVEUSDT · venue disagrees · exchange 0 AAVE, ledger 0.82 AAVE · last compared 21:39:12 UTC · See the pending decision",
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

    await venueLink("See the pending decision, AAVEUSDT");
    expect(line.textContent).toBe(
      "AAVEUSDT · venue disagrees · exchange 90 AAVE, ledger 150 AAVE · last compared 21:39:12 UTC · shared by 2 positions on this pair · See the pending decision",
    );
  });

  it("leaves the shared part out, with its separator, for a count of one", async () => {
    await mountVenue();
    const line = venueLine("Venue disagrees, AAVEUSDT");

    await venueLink("See the pending decision, AAVEUSDT");
    expect(line.textContent).not.toContain("shared by");
    expect(line.textContent).not.toContain(" ·  · ");
  });

  it("is a group named for the pair, and its link is a real link named for the pair", async () => {
    await mountVenue();

    const link = await venueLink("See the pending decision, AAVEUSDT");
    expect(link).toHaveAttribute("href", "/#decision-rail");
    expect(link).toHaveTextContent("See the pending decision");
    expect(venueLine("Venue disagrees, AAVEUSDT")).toContainElement(link);
  });

  it("reads the same line in Spanish, with the fixed Spanish words", async () => {
    await act(() => i18n.changeLanguage("es"));
    await mountVenue();
    const line = venueLine("El exchange no coincide, AAVEUSDT");

    await venueLink("Ver la decisión pendiente, AAVEUSDT");
    expect(line.textContent).toBe(
      "AAVEUSDT · el exchange no coincide · exchange 0 AAVE, libro mayor 0.82 AAVE · última comparación 21:39:12 UTC · Ver la decisión pendiente",
    );
  });

  it("reads the shared part in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    const base = disagreeing();
    await mountVenue(disagreeing({ venue_disagreement: { ...base.venue_disagreement!, allocation_count: 2 } }));
    const line = venueLine("El exchange no coincide, AAVEUSDT");

    await venueLink("Ver la decisión pendiente, AAVEUSDT");
    expect(line).toHaveTextContent("compartida por 2 posiciones en este par");
  });
});
