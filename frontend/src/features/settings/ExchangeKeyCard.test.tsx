import { fireEvent, render, screen, within } from "@testing-library/react";
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

// ---------------------------------------------------------------------------------------------
// The tags (design § D): what is known about a stored key, in the order they are drawn.
// ---------------------------------------------------------------------------------------------

const DAY = "2026-10-02T09:30:00Z";
const OTHER_DAY = "2026-10-03T09:30:00Z";
const FACTS = "What is known about this key";
const CONFIRMED_HINT =
  "\"Confirmed\" is what you told this panel on that day. Binance does not let the panel check what a key may do, so orders are sent on your confirmation. If the key cannot trade futures, Binance rejects the first live order and you get a Telegram alert. Nothing checks the withdrawal setting.";
const UNRECORDED_HINT = "Stored before the system recorded how a key was checked. Enter it again to have it checked.";

/** A Binance key whose trade and withdrawal facts are the owner's word, each with its own day. */
function confirmed(overrides: Record<string, unknown> = {}): CredentialEntry {
  return stored("binance", {
    trade_capability_source: "OWNER_CONFIRMED",
    trade_confirmed_at: DAY,
    withdraw_check: "OWNER_CONFIRMED",
    withdraw_confirmed_at: OTHER_DAY,
    internal_transfer: null,
    ...overrides,
  });
}

/** A key stored before the system recorded how it was checked (migration 0027). */
function unrecorded(overrides: Record<string, unknown> = {}): CredentialEntry {
  return stored("binance", {
    trade_capability_source: "UNRECORDED",
    withdraw_check: "UNRECORDED",
    validated_at: null,
    trade_confirmed_at: null,
    withdraw_confirmed_at: null,
    internal_transfer: null,
    ...overrides,
  });
}

function factsList(): HTMLElement {
  const list = screen.queryByRole("list", { name: FACTS });
  expect(list, FACTS).toBeInTheDocument();
  return list as HTMLElement;
}

/** The tags, in order: every list item that is not the information button. */
function tags(): HTMLElement[] {
  return within(factsList())
    .getAllByRole("listitem")
    .filter((item) => item.querySelector("button") === null);
}

function tagTexts(): string[] {
  return tags().map((item) => item.textContent ?? "");
}

describe("the tags of a key checked by the venue", () => {
  it("test_verified_key_shows_trades_no_withdrawal_and_transfers_or_no_transfers", () => {
    renderCard({ exchange: "bybit", entry: stored("bybit", { internal_transfer: true }) });
    expect(tagTexts()).toEqual(["trades", "no withdrawal", "transfers"]);
  });

  it("says `no transfers` when internal transfers are not allowed", () => {
    renderCard({ exchange: "bybit", entry: stored("bybit", { internal_transfer: false }) });
    expect(tagTexts()).toEqual(["trades", "no withdrawal", "no transfers"]);
  });

  it("draws no transfer tag when it is not known", () => {
    renderCard({ exchange: "bybit", entry: stored("bybit", { internal_transfer: null }) });
    expect(tagTexts()).toEqual(["trades", "no withdrawal"]);
  });

  it("draws no capability tag for a verified key that cannot trade: the read-only mark says it", () => {
    renderCard({ exchange: "bybit", entry: stored("bybit", { trade_capable: false, internal_transfer: false }) });
    expect(tagTexts()).toEqual(["read-only", "no withdrawal", "no transfers"]);
  });
});

describe("the capability and withdrawal tags never claim more than was checked", () => {
  it("draws `reads` for a trade fact the venue did not check when the key was validated", () => {
    renderCard({ exchange: "binance", entry: unrecorded({ validated_at: DAY }) });
    expect(tagTexts()).toEqual(["reads", "trade not verified", "withdraw not verified"]);
  });

  it("draws no capability tag when the trade fact was not checked and there is no validation day", () => {
    renderCard({ exchange: "binance", entry: unrecorded() });
    expect(tagTexts()).toEqual(["trade not verified", "withdraw not verified"]);
  });

  it.each(["OWNER_CONFIRMED", "UNRECORDED", "SOMETHING_NEW"])(
    "draws `no withdrawal` never for the withdraw source %s",
    (source) => {
      renderCard({ exchange: "binance", entry: confirmed({ withdraw_check: source }) });
      expect(tagTexts()).not.toContain("no withdrawal");
      expect(screen.queryByText("no withdrawal")).not.toBeInTheDocument();
    },
  );

  it("draws a source value it does not know as not verified, never as trades or no withdrawal", () => {
    renderCard({
      exchange: "binance",
      entry: stored("binance", {
        trade_capability_source: "FROM_THE_FUTURE",
        withdraw_check: "FROM_THE_FUTURE",
        trade_confirmed_at: DAY,
        withdraw_confirmed_at: DAY,
      }),
    });

    const texts = tagTexts();
    expect(texts).toContain("trade not verified");
    expect(texts).toContain("withdraw not verified");
    expect(texts).not.toContain("trades");
    expect(texts).not.toContain("no withdrawal");
    expect(texts.some((text) => text.includes("confirmed"))).toBe(false);
  });

  it("draws a confirmation with no day as not verified: `confirmed` cannot be said without the day", () => {
    renderCard({ exchange: "binance", entry: confirmed({ trade_confirmed_at: null, withdraw_confirmed_at: null }) });

    expect(tagTexts()).toEqual(["reads", "trade not verified", "withdraw not verified"]);
    expect(screen.queryByRole("button", { name: "About what you confirmed" })).not.toBeInTheDocument();
  });
});

describe("a key the owner confirmed", () => {
  it("test_owner_confirmed_key_shows_trade_confirmed_and_withdraw_confirmed_with_their_dates_and_never_not_verified_nor_no_withdrawal", () => {
    const card = renderCard({ exchange: "binance", entry: confirmed({ validated_at: DAY }) });

    expect(textNode("key ending in 7Q2d")).toBeInTheDocument();
    expect(textNode("checked Oct 2, 2026")).toBeInTheDocument();
    expect(tagTexts()).toEqual(["reads", "trade confirmed Oct 2, 2026", "withdraw confirmed Oct 3, 2026"]);
    // The information button is the last item of the list, a button and not a tag.
    const items = within(factsList()).getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(within(items[3] as HTMLElement).queryByRole("button", { name: "About what you confirmed" })).toBeInTheDocument();
    expect(card.textContent).not.toContain("not verified");
    expect(card.textContent).not.toContain("no withdrawal");
    expect(card.textContent).not.toContain("trades");
    expect(card.outerHTML).not.toMatch(AMBER);
  });

  it("is the only control of the card and opens the text that says the withdrawal setting is not checked", () => {
    renderCard({ exchange: "binance", entry: confirmed() });

    const buttons = screen.queryAllByRole("button");
    expect(buttons.map((button) => button.getAttribute("aria-label"))).toEqual(["About what you confirmed"]);
    const button = buttons[0] as HTMLElement;
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(CONFIRMED_HINT)).not.toBeInTheDocument();

    fireEvent.click(button);

    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByText(CONFIRMED_HINT)).toBeInTheDocument();
    expect(screen.queryByText(/Nothing checks the withdrawal setting/)).toBeInTheDocument();

    fireEvent.click(button);
    expect(screen.queryByText(CONFIRMED_HINT)).not.toBeInTheDocument();
  });

  it("draws the information button for one confirmed fact too", () => {
    renderCard({ exchange: "binance", entry: confirmed({ trade_confirmed_at: null }) });

    expect(tagTexts()).toEqual(["reads", "trade not verified", "withdraw confirmed Oct 3, 2026"]);
    expect(screen.queryByRole("button", { name: "About what you confirmed" })).toBeInTheDocument();
  });

  it("draws no information button for a key the venue checked, nor for one with nothing on record", () => {
    renderCard({ exchange: "bybit", entry: stored("bybit") });
    expect(screen.queryAllByRole("button")).toEqual([]);
  });
});

describe("a key with no recorded facts", () => {
  it("test_unrecorded_key_shows_not_validated_and_both_not_verified_tags_and_never_confirmed", () => {
    const card = renderCard({ exchange: "binance", entry: unrecorded() });

    expect(textNode("not validated")).toBeInTheDocument();
    expect(tagTexts()).toEqual(["trade not verified", "withdraw not verified"]);
    expect(card.textContent).not.toContain("confirmed");
    const hint = textNode(UNRECORDED_HINT);
    expect(hint).toHaveClass("text-ink-3");
    expect(screen.queryAllByRole("button")).toEqual([]);
    expect(card).toHaveClass("border-rule");
    expect(card.outerHTML).not.toMatch(AMBER);
  });

  it("does not tell the owner to enter the key again on an exchange the panel does not manage", () => {
    renderCard({ exchange: "pionex", entry: unrecorded(), served: false });

    expect(screen.queryByText(UNRECORDED_HINT)).not.toBeInTheDocument();
    expect(screen.queryByText(NOT_SERVED_SENTENCE)).toBeInTheDocument();
  });
});

describe("one phrase per fact (decision 55)", () => {
  const SOURCES = ["VERIFIED", "OWNER_CONFIRMED", "UNRECORDED", "FROM_THE_FUTURE"];
  const DATES = [DAY, null];

  it("test_one_phrase_per_fact: exactly one trade tag and one withdrawal tag, and never `confirmed` with `not verified`", () => {
    let rendered = 0;
    for (const tradeSource of SOURCES) {
      for (const tradeCapable of [true, false]) {
        // A key that cannot trade is a fact only the venue states; the owner's word makes a key capable.
        if (!tradeCapable && tradeSource !== "VERIFIED") continue;
        for (const validatedAt of DATES) {
          for (const tradeConfirmedAt of DATES) {
            for (const withdrawSource of SOURCES) {
              for (const withdrawConfirmedAt of DATES) {
                const entry = stored("binance", {
                  trade_capable: tradeCapable,
                  trade_capability_source: tradeSource,
                  validated_at: validatedAt,
                  trade_confirmed_at: tradeConfirmedAt,
                  withdraw_check: withdrawSource,
                  withdraw_confirmed_at: withdrawConfirmedAt,
                });
                const { unmount } = render(<ExchangeKeyCard exchange="binance" entry={entry} poolOn={false} served />);
                const texts = tagTexts();
                const label = JSON.stringify({ tradeSource, tradeCapable, validatedAt, tradeConfirmedAt, withdrawSource, withdrawConfirmedAt });

                const trade = texts.filter((text) => /^(trades|read-only|trade confirmed .+|trade not verified)$/.test(text));
                const withdrawal = texts.filter((text) => /^(no withdrawal|withdraw confirmed .+|withdraw not verified)$/.test(text));
                expect(trade, label).toHaveLength(1);
                expect(withdrawal, label).toHaveLength(1);
                expect(texts.filter((text) => /^trade (confirmed|not verified)/.test(text)).length, label).toBeLessThanOrEqual(1);
                expect(texts.filter((text) => /^withdraw (confirmed|not verified)/.test(text)).length, label).toBeLessThanOrEqual(1);
                // The only tags that exist at all are the ones of the table.
                for (const text of texts) {
                  expect(text, label).toMatch(
                    /^(read-only|reads|trades|no withdrawal|transfers|no transfers|trade confirmed .+|trade not verified|withdraw confirmed .+|withdraw not verified)$/,
                  );
                }
                unmount();
                rendered += 1;
              }
            }
          }
        }
      }
    }
    expect(rendered).toBeGreaterThan(100);
  });

  it("test_confirmed_and_not_verified_tags_are_neutral_not_amber", () => {
    for (const entry of [confirmed(), unrecorded(), confirmed({ trade_confirmed_at: null })]) {
      const { unmount } = render(<ExchangeKeyCard exchange="binance" entry={entry} poolOn={false} served />);
      const card = screen.getByRole("article");
      expect(card.outerHTML).not.toMatch(AMBER);
      expect(card).toHaveClass("border-rule");
      unmount();
    }
  });
});

describe("the three looks of a tag differ in more than colour", () => {
  it("draws what the venue showed as a filled tag", () => {
    renderCard({ exchange: "bybit", entry: stored("bybit", { internal_transfer: true }) });

    for (const tag of tags()) {
      expect(tag, tag.textContent ?? "").toHaveClass("border-rule", "bg-panel-2", "text-ink-2");
      expect(tag).not.toHaveClass("border-dashed");
    }
  });

  it("draws the owner's word as a dashed, hollow tag", () => {
    renderCard({ exchange: "binance", entry: confirmed() });

    const [reads, trade, withdraw] = tags() as [HTMLElement, HTMLElement, HTMLElement];
    expect(reads).toHaveClass("border-rule", "bg-panel-2", "text-ink-2");
    for (const tag of [trade, withdraw]) {
      expect(tag).toHaveClass("border-dashed", "border-rule-strong", "text-ink-2");
      expect(tag).not.toHaveClass("bg-panel-2");
      expect(tag).not.toHaveClass("text-ink-3");
    }
  });

  it("draws a fact with nothing on record as a dashed, dimmer tag", () => {
    renderCard({ exchange: "binance", entry: unrecorded() });

    for (const tag of tags()) {
      expect(tag).toHaveClass("border-dashed", "border-rule-strong", "text-ink-3");
      expect(tag).not.toHaveClass("text-ink-2");
      expect(tag).not.toHaveClass("bg-panel-2");
    }
  });
});

describe("the structure that keeps the tags whole at every width (jsdom has no layout)", () => {
  it("is a list that wraps, whose tags are unbreakable list items, with no separator character in the card", () => {
    const card = renderCard({ exchange: "binance", entry: confirmed({ validated_at: DAY }) });

    const list = factsList();
    expect(list.tagName).toBe("UL");
    expect(list).toHaveClass("flex", "flex-wrap");
    for (const tag of tags()) {
      expect(tag.tagName).toBe("LI");
      expect(tag).toHaveClass("whitespace-nowrap", "rounded", "border", "px-2", "py-0.5", "font-mono", "text-xs");
    }
    expect(card.textContent).not.toContain(" · ");
  });

  it("keeps the checked day out of the tags", () => {
    renderCard({ exchange: "bybit", entry: stored("bybit") });

    expect(factsList()).not.toHaveTextContent("Oct 2, 2026");
    expect(textNode("checked Oct 2, 2026").closest("ul")).toBeNull();
  });
});

describe("the card in Spanish, with the fixed texts of design § J", () => {
  it("writes the tags of a key the venue checked", async () => {
    await i18n.changeLanguage("es");
    renderCard({ exchange: "bybit", entry: stored("bybit", { internal_transfer: true }) });

    expect(textNode("clave terminada en 7Q2d")).toBeInTheDocument();
    expect(textNode("comprobada el 2 oct 2026")).toBeInTheDocument();
    expect(tagTexts()).toEqual(["opera", "sin retiros", "transfiere"]);
  });

  it("writes `sin transferencias` and `solo lectura`", async () => {
    await i18n.changeLanguage("es");
    renderCard({ exchange: "bybit", entry: stored("bybit", { trade_capable: false, internal_transfer: false }) });

    expect(tagTexts()).toEqual(["solo lectura", "sin retiros", "sin transferencias"]);
  });

  it("writes the owner's confirmations with their days, and the information button", async () => {
    await i18n.changeLanguage("es");
    renderCard({ exchange: "binance", entry: confirmed() });

    expect(tagTexts()).toEqual(["lee", "operar: confirmado el 2 oct 2026", "retiros: confirmado el 3 oct 2026"]);
    const button = screen.queryByRole("button", { name: "Sobre lo que usted confirmó" });
    expect(button).toBeInTheDocument();
    fireEvent.click(button as HTMLElement);
    expect(
      screen.queryByText(
        "«Confirmado» es lo que usted indicó a este panel ese día. Binance no permite que el panel compruebe qué puede hacer una clave, así que las órdenes se envían con su confirmación. Si la clave no puede operar futuros, Binance rechaza la primera orden real y usted recibe una alerta de Telegram. Nada comprueba el ajuste de retiros.",
      ),
    ).toBeInTheDocument();
  });

  it("writes the facts with nothing on record, and the sentence that says to enter the key again", async () => {
    await i18n.changeLanguage("es");
    renderCard({ exchange: "binance", entry: unrecorded() });

    expect(textNode("sin validar")).toBeInTheDocument();
    expect(tagTexts()).toEqual(["operar: sin verificar", "retiros: sin verificar"]);
    expect(screen.queryByRole("list", { name: "Lo que se sabe de esta clave" })).toBeInTheDocument();
    expect(screen.queryByText(UNRECORDED_HINT)).not.toBeInTheDocument();
  });

  it("writes the month of a long date as the language does", async () => {
    await i18n.changeLanguage("es");
    renderCard({
      exchange: "binance",
      entry: confirmed({ withdraw_confirmed_at: "2026-09-30T09:30:00Z" }),
    });

    expect(tagTexts()).toContain("retiros: confirmado el 30 sept 2026");
  });
});
