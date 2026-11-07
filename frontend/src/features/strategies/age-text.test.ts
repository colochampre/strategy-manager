import { describe, expect, it } from "vitest";

import { ageParts, ageText } from "@/features/strategies/age-text";
import i18n from "@/shared/i18n";

const at = (iso: string) => new Date(iso);

describe("ageParts", () => {
  it.each([
    ["the same instant", "2026-11-06T10:00:00Z", "2026-11-06T10:00:00Z", { years: 0, months: 0, days: 0 }],
    ["a day short of an hour", "2026-11-05T10:00:00Z", "2026-11-06T09:00:00Z", { years: 0, months: 0, days: 0 }],
    ["six whole days", "2026-10-31T10:00:00Z", "2026-11-06T10:00:00Z", { years: 0, months: 0, days: 6 }],
    ["one calendar month to the day", "2026-10-06T10:00:00Z", "2026-11-06T10:00:00Z", { years: 0, months: 1, days: 0 }],
    ["a month and some days", "2026-09-20T10:00:00Z", "2026-11-06T10:00:00Z", { years: 0, months: 1, days: 17 }],
    ["one hour short of a month", "2026-10-06T11:00:00Z", "2026-11-06T10:00:00Z", { years: 0, months: 0, days: 30 }],
    ["the 31st into a short month", "2026-01-31T10:00:00Z", "2026-02-28T10:00:00Z", { years: 0, months: 1, days: 0 }],
    ["a year and four months", "2025-07-01T10:00:00Z", "2026-11-06T10:00:00Z", { years: 1, months: 4, days: 5 }],
    ["two whole years", "2024-11-06T10:00:00Z", "2026-11-06T10:00:00Z", { years: 2, months: 0, days: 0 }],
    ["a start after now, read as nothing yet", "2026-11-07T10:00:00Z", "2026-11-06T10:00:00Z", { years: 0, months: 0, days: 0 }],
  ])("%s", (_case, from, to, parts) => {
    expect(ageParts(at(from), at(to))).toEqual(parts);
  });
});

describe("ageText", () => {
  it.each([
    [{ years: 0, months: 0, days: 0 }, "0d", "0d"],
    [{ years: 0, months: 0, days: 6 }, "6d", "6d"],
    [{ years: 0, months: 1, days: 0 }, "1mo", "1m"],
    [{ years: 0, months: 4, days: 12 }, "4mo 12d", "4m 12d"],
    [{ years: 1, months: 0, days: 9 }, "1y", "1a"],
    [{ years: 1, months: 4, days: 5 }, "1y 4mo", "1a 4m"],
  ])("writes %o as the two largest units, in English and Spanish", (parts, english, spanish) => {
    expect(ageText(i18n.getFixedT("en"), parts)).toBe(english);
    expect(ageText(i18n.getFixedT("es"), parts)).toBe(spanish);
  });
});
