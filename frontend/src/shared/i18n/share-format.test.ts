import { describe, expect, it } from "vitest";

import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";

describe("a seat's share", () => {
  it("is written 20% in both languages, with no space before the sign (L.10)", () => {
    expect(en.strategies.subscriptions.shareValue).toBe("{{share}}%");
    expect(es.strategies.subscriptions.shareValue).toBe("{{share}}%");
  });
});
