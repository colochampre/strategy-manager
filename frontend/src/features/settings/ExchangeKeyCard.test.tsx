import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ExchangeKeyCard, type ExchangeKeyCardProps } from "@/features/settings/ExchangeKeyCard";
import type { CredentialEntry } from "@/shared/api/credentials";
import i18n from "@/shared/i18n";
import { emptyKey, storedKey } from "@/test/harness";

afterEach(async () => {
  await i18n.changeLanguage("en");
});

/** Amber, in any utility: the card may carry it only where the owner has something to do. */
const AMBER = /\b(?:bg|text|border|ring|outline|fill|stroke|divide)-decision\b/;

const READ_ONLY_SENTENCE =
  "This key cannot trade. With dry run off, opening signals for Bybit are refused until you add a key that can trade futures.";
const DEGRADED_SENTENCE =
  "No key stored. With dry run off, opening signals for Binance are refused until a key is added.";
const EMPTY_SENTENCE = "No key stored. Add one to read and trade on Binance from here.";
const NOT_SERVED_SENTENCE =
  "The Pionex key is managed outside this panel, on the server. It cannot be added, replaced or deleted here.";

/** A `STORED` row as the API sends it, typed; the overrides replace any of its fields. */
function stored(exchange: string, overrides: Record<string, unknown> = {}): CredentialEntry {
  return storedKey(exchange, {
    last4: "7Q2d",
    validated_at: "2026-10-02T09:30:00Z",
    ...overrides,
  }) as unknown as CredentialEntry;
}

function empty(exchange: string): CredentialEntry {
  return emptyKey(exchange) as unknown as CredentialEntry;
}

/** The element holding a text. A missing one fails here as an assertion, not as a query error. */
function textNode(text: string): HTMLElement {
  const node = screen.queryByText(text);
  expect(node, text).toBeInTheDocument();
  return node as HTMLElement;
}

function renderCard(overrides: Partial<ExchangeKeyCardProps> & Pick<ExchangeKeyCardProps, "exchange">): HTMLElement {
  const props: ExchangeKeyCardProps = { entry: undefined, poolOn: false, served: true, ...overrides };
  render(<ExchangeKeyCard {...props} />);
  return screen.getByRole("article");
}

describe("the card's shell", () => {
  it.each([
    ["bybit", "Bybit"],
    ["binance", "Binance"],
    ["pionex", "Pionex"],
    ["kraken", "kraken"],
  ])("is an article named by its one h3, the proper name of %s: %s", (exchange, name) => {
    renderCard({ exchange, entry: stored(exchange) });

    expect(screen.queryByRole("article", { name })).toBeInTheDocument();
    const headings = screen.getAllByRole("heading");
    expect(headings).toHaveLength(1);
    expect(headings[0]).toHaveTextContent(name);
    expect(headings[0]?.tagName).toBe("H3");
  });

  it("has the card's classes and the grid that puts the actions beside the head from sm", () => {
    const card = renderCard({ exchange: "bybit", entry: stored("bybit") });

    expect(card).toHaveClass("bg-panel", "border", "border-rule", "rounded-lg", "p-5");
    expect(card).toHaveClass("grid", "grid-cols-1", "sm:grid-cols-[minmax(0,1fr)_auto]", "items-start");
    const areas = Array.from(card.children);
    expect(areas[0]).toContainElement(screen.getByRole("heading"));
    expect(areas[1]).toHaveClass("sm:col-span-2");
    expect(areas[2]).toHaveClass("sm:col-start-2", "sm:row-start-1");
  });
});

describe("the key line", () => {
  it("is a paragraph that is not a heading, with the label, four dots and the last four, hidden from assistive technology", () => {
    renderCard({ exchange: "bybit", entry: stored("bybit") });

    const hint = textNode("7Q2d").closest("p") as HTMLElement;
    expect(hint.tagName).toBe("P");
    expect(hint).toHaveClass("font-mono", "text-xl", "font-semibold", "whitespace-nowrap");
    expect(screen.getAllByRole("heading")).toHaveLength(1);

    const visible = textNode("7Q2d").closest('[aria-hidden="true"]') as HTMLElement;
    expect(visible).toBeInTheDocument();
    expect(hint).toContainElement(visible);
    expect(visible.textContent).toBe("key ••••7Q2d");
    // The label and the dots are inside the same hidden subtree, not read out.
    expect(textNode("••••").closest('[aria-hidden="true"]')).toBe(visible);
    expect(textNode("key").closest('[aria-hidden="true"]')).toBe(visible);
    // The characters are the only part in `ink`.
    expect(textNode("7Q2d")).toHaveClass("text-ink", "tracking-wider");
    expect(textNode("••••")).toHaveClass("text-ink-3", "font-normal");
    // A text says it in words, and the hidden subtree is not it.
    const words = textNode("key ending in 7Q2d");
    expect(hint).toContainElement(words);
    expect(words.closest('[aria-hidden="true"]')).toBeNull();
    expect(words).toHaveClass("sr-only");
  });

  it("never holds more than the four characters the API sent", () => {
    renderCard({ exchange: "bybit", entry: stored("bybit") });

    expect(textNode("7Q2d").textContent).toHaveLength(4);
    expect(textNode("key ending in 7Q2d").textContent).toBe("key ending in 7Q2d");
  });

  it("puts the checked day beside the hint, in a second unbreakable paragraph", () => {
    renderCard({ exchange: "bybit", entry: stored("bybit") });

    const hint = textNode("7Q2d").closest("p") as HTMLElement;
    const date = textNode("checked Oct 2, 2026");
    expect(date.tagName).toBe("P");
    expect(date).toHaveClass("font-mono", "text-xs", "text-ink-3", "whitespace-nowrap");
    expect(date.parentElement).toBe(hint.parentElement);
    expect(date.parentElement).toHaveClass("flex", "flex-wrap", "items-baseline", "gap-x-3", "gap-y-0.5");
    expect(screen.queryByText("not validated")).not.toBeInTheDocument();
  });

  it("says `not validated` when the key has no validation day", () => {
    renderCard({ exchange: "bybit", entry: stored("bybit", { validated_at: null }) });

    const note = textNode("not validated");
    expect(note).toHaveClass("font-mono", "text-xs", "text-ink-3", "whitespace-nowrap");
    expect(screen.queryByText(/^checked /)).not.toBeInTheDocument();
    // The hint is still the key's own four characters, never an invented key.
    expect(screen.queryByText("7Q2d")).toBeInTheDocument();
  });

  it("holds the `no key` mark as a tag, and no hint and no date, when no key is stored", () => {
    renderCard({ exchange: "binance", entry: empty("binance"), poolOn: false });

    expect(screen.queryByText("no key")).toBeInTheDocument();
    expect(screen.queryByText(/key ending in/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^checked /)).not.toBeInTheDocument();
    expect(screen.queryByText("not validated")).not.toBeInTheDocument();
  });
});

describe("a key checked by the venue", () => {
  it("test_a_key_checked_by_the_venue_is_neutral_and_unmarked", () => {
    const card = renderCard({ exchange: "bybit", entry: stored("bybit") });

    expect(screen.queryByText("key ending in 7Q2d")).toBeInTheDocument();
    expect(screen.queryByText("checked Oct 2, 2026")).toBeInTheDocument();
    expect(card).toHaveClass("border-rule");
    expect(card).not.toHaveClass("border-decision");
    expect(card.outerHTML).not.toMatch(AMBER);
    expect(screen.queryByText("read-only")).not.toBeInTheDocument();
    expect(screen.queryByText(/This key cannot trade/)).not.toBeInTheDocument();
    expect(screen.queryByText(/No key stored/)).not.toBeInTheDocument();
    expect(screen.queryByText(/managed outside this panel/)).not.toBeInTheDocument();
  });
});

describe("the states that ask the owner to act are amber, the rest are neutral", () => {
  it("test_readonly_key_shows_amber_border_and_cannot_trade_sentence", () => {
    const card = renderCard({ exchange: "bybit", entry: stored("bybit", { trade_capable: false }) });

    const sentence = screen.queryByText(READ_ONLY_SENTENCE);
    expect(sentence).toBeInTheDocument();
    expect(sentence).toHaveClass("text-decision");
    expect(card).toHaveClass("border-decision");
    expect(card).not.toHaveClass("border-rule");
    const mark = screen.queryByText("read-only");
    expect(mark).toBeInTheDocument();
    expect(mark).toHaveClass("border-decision", "text-decision");
  });

  it("test_degraded_no_key_but_enabled_pool_shows_amber_border_and_no_key_stored_sentence", () => {
    const card = renderCard({ exchange: "binance", entry: empty("binance"), poolOn: true });

    const sentence = screen.queryByText(DEGRADED_SENTENCE);
    expect(sentence).toBeInTheDocument();
    expect(sentence).toHaveClass("text-decision");
    expect(card).toHaveClass("border-decision");
    expect(screen.queryByText("no key")).toHaveClass("border-decision", "text-decision");
  });

  it("gives an exchange the API does not list at all the same degraded card", () => {
    const card = renderCard({ exchange: "binance", entry: undefined, poolOn: true });

    expect(screen.queryByText(DEGRADED_SENTENCE)).toBeInTheDocument();
    expect(card).toHaveClass("border-decision");
  });

  it.each([
    ["an exchange that never had a key", undefined],
    ["a key that was deleted (an EMPTY row)", empty("binance")],
  ])("test_no_key_ever_stored_shows_neutral_empty_state_no_amber_border: %s", (_label, entry) => {
    const card = renderCard({ exchange: "binance", entry, poolOn: false });

    const sentence = screen.queryByText(EMPTY_SENTENCE);
    expect(sentence).toBeInTheDocument();
    expect(sentence).not.toHaveClass("text-decision");
    expect(card).toHaveClass("border-rule");
    expect(card).not.toHaveClass("border-decision");
    expect(screen.queryByText("no key")).toHaveClass("border-rule-strong", "text-ink-3");
    expect(card.outerHTML).not.toMatch(AMBER);
  });

  it("is neutral, not amber, when the pools are unknown: nothing is claimed on a guess", () => {
    const card = renderCard({ exchange: "binance", entry: empty("binance"), poolOn: null });

    expect(screen.queryByText(EMPTY_SENTENCE)).toBeInTheDocument();
    expect(card).toHaveClass("border-rule");
    expect(card.outerHTML).not.toMatch(AMBER);
  });
});

describe("an exchange the panel does not manage", () => {
  it("has no button and says so in ink-3, with a key stored (2h)", () => {
    const card = renderCard({ exchange: "pionex", entry: stored("pionex"), poolOn: true, served: false });

    const sentence = screen.queryByText(NOT_SERVED_SENTENCE);
    expect(sentence).toBeInTheDocument();
    expect(sentence).toHaveClass("text-ink-3");
    expect(within(card).queryAllByRole("button")).toEqual([]);
    expect(card.outerHTML).not.toMatch(AMBER);
  });

  it("has no button and says `No key stored.` and then the same sentence, with no key (2i)", () => {
    const card = renderCard({ exchange: "pionex", entry: undefined, poolOn: false, served: false });

    expect(screen.queryByText("No key stored.")).toBeInTheDocument();
    expect(screen.queryByText(NOT_SERVED_SENTENCE)).toHaveClass("text-ink-3");
    expect(screen.queryByText(/Add one to read and trade/)).not.toBeInTheDocument();
    expect(within(card).queryAllByRole("button")).toEqual([]);
    expect(card.outerHTML).not.toMatch(AMBER);
  });

  it("is amber only when a pool of it is on", () => {
    const card = renderCard({ exchange: "pionex", entry: undefined, poolOn: true, served: false });

    expect(card).toHaveClass("border-decision");
    expect(screen.queryByText("no key")).toHaveClass("text-decision");
    // The sentence that says it cannot be managed here is still quiet.
    expect(screen.queryByText(NOT_SERVED_SENTENCE)).toHaveClass("text-ink-3");
    expect(within(card).queryAllByRole("button")).toEqual([]);
  });
});

describe("this unit draws no control", () => {
  // The Binance information button belongs to the tags and is pinned with them (task 13.4.4).
  it("test_no_card_has_a_button_in_this_unit", () => {
    const cases: [string, CredentialEntry | undefined, boolean | null, boolean][] = [
      ["bybit", stored("bybit"), false, true],
      ["bybit", stored("bybit", { trade_capable: false }), true, true],
      ["bybit", stored("bybit", { validated_at: null }), false, true],
      ["binance", empty("binance"), true, true],
      ["binance", undefined, false, true],
      ["binance", undefined, null, true],
      ["pionex", stored("pionex"), true, false],
      ["pionex", undefined, false, false],
    ];
    for (const [exchange, entry, poolOn, served] of cases) {
      const { unmount } = render(<ExchangeKeyCard exchange={exchange} entry={entry} poolOn={poolOn} served={served} />);
      expect(screen.queryAllByRole("button"), `${exchange} ${entry?.status}`).toEqual([]);
      unmount();
    }
  });
});

describe("test_card_never_renders_a_raw_permissions_payload", () => {
  it("draws nothing of a field it does not know, however the API names it", () => {
    const card = renderCard({
      exchange: "bybit",
      entry: stored("bybit", {
        permissions: { withdraw: "SENTINEL-PERMISSION-WITHDRAW", contract: ["SENTINEL-PERMISSION-CONTRACT"] },
        api_key: "SENTINEL-API-KEY-0123456789",
        label: "SENTINEL-LABEL",
      }),
    });

    expect(card.textContent).not.toContain("SENTINEL");
    expect(card.outerHTML).not.toContain("SENTINEL");
    expect(card.textContent).not.toContain("0123456789");
  });
});
