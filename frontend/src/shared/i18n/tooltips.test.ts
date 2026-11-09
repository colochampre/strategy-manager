import { describe, expect, it } from "vitest";

import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";

/**
 * Every text that reaches a tooltip (an `IconTip` label, a `Tooltip`'s text, an `IconButton` label, a
 * `StatusButton` `iconOnly` text): the owner asked for each to begin with a capital and be brief (tasks.md L.9).
 */
const TOOLTIP_KEYS = [
  // The ledger's and the record line's icons.
  "overview.ledger.available",
  "overview.ledger.pnl",
  "overview.ledger.pnlRange",
  "overview.ledger.return",
  "overview.ledger.returnRange",
  "overview.ledger.deepest",
  "strategies.performance.contribution",
  "strategies.performance.contributionRange",
  "strategies.report.recordReturn",
  "strategies.report.recordReturnRange",
  // The cards' icons, and the public figures'.
  "strategies.card.age",
  "strategies.card.subscribed",
  "strategies.card.uptime",
  "strategies.card.uptimeAtLeast",
  "strategies.card.neverEnabled",
  "strategies.card.trades",
  "strategies.card.return",
  "strategies.card.deepest",
  "strategies.card.winRate",
  "strategies.card.subscribers",
  "strategies.card.capital",
  "strategies.card.pnl",
  "strategies.card.share",
  "strategies.card.leverage",
  // Archive's reason, and the icon buttons' names.
  "strategies.archive.disabledHint",
  "settings.name.save",
  "settings.name.saving",
  "settings.name.saved",
  "settings.form.submit",
  "settings.form.submitting",
  "strategies.detail.pairs.save",
  "strategies.detail.pairs.saving",
  "strategies.detail.saved",
  "strategies.detail.share.save",
  "strategies.detail.share.saving",
  "strategies.description.save",
  "strategies.description.saving",
  "strategies.leverage.save",
  "strategies.leverage.saving",
  "strategies.detail.name.save",
  "strategies.detail.name.saving",
  "strategies.webhook.copied",
  "strategies.sharing.copyLink",
  "strategies.sharing.copyCode",
  "settings.card.delete",
  "strategies.delete.button",
] as const;

function lookup(locale: unknown, key: string): unknown {
  let value = locale;
  for (const part of key.split(".")) {
    if (typeof value !== "object" || value === null) return undefined;
    value = (value as Record<string, unknown>)[part];
  }
  return value;
}

describe("the tooltips", () => {
  it.each(TOOLTIP_KEYS)("%s begins with a capital in English and in Spanish", (key) => {
    for (const [name, locale] of [["en", en], ["es", es]] as const) {
      const text = lookup(locale, key);
      expect(typeof text, `${name} ${key}`).toBe("string");
      const first = (text as string).charAt(0);
      expect(first, `${name} ${key}`).not.toBe(first.toLowerCase());
      expect(first, `${name} ${key}`).toBe(first.toUpperCase());
    }
  });

  it("are brief: no sentence, no full stop", () => {
    for (const key of TOOLTIP_KEYS) {
      for (const locale of [en, es]) {
        const text = lookup(locale, key) as string;
        expect(text, key).not.toMatch(/[.!?]$/);
        expect(text.length, key).toBeLessThanOrEqual(56);
      }
    }
  });

  it("writes Archive's reason as an instruction, in the polite form in Spanish", () => {
    expect(lookup(en, "strategies.archive.disabledHint")).toBe("Disable it and close its positions first");
    expect(lookup(es, "strategies.archive.disabledHint")).toBe("Primero desactívela y cierre sus posiciones");
  });
});
