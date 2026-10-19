import { afterEach, describe, expect, it } from "vitest";

import { exchangeName } from "@/shared/exchanges/exchange-name";
import i18n from "@/shared/i18n";

afterEach(async () => {
  await i18n.changeLanguage("en");
});

describe("exchangeName", () => {
  it("names a known exchange by its entry", () => {
    expect(["binance", "bybit", "pionex"].map((id) => exchangeName(i18n.t, i18n, id))).toEqual([
      "Binance",
      "Bybit",
      "Pionex",
    ]);
  });

  it("capitalises an exchange no entry names, in both languages (owner decision 77, Q2)", async () => {
    const english = exchangeName(i18n.t, i18n, "kraken");
    await i18n.changeLanguage("es");
    expect([english, exchangeName(i18n.t, i18n, "kraken")]).toEqual(["Kraken", "Kraken"]);
  });
});
