import type { TFunction, i18n as I18nInstance } from "i18next";

/**
 * The exchange's proper name from `exchanges.<id>`. An id with no entry is shown with a capital initial (owner
 * decision 77, Q2), never as the API spells it. Display only: every comparison keeps using the id.
 */
export function exchangeName(t: TFunction, i18n: I18nInstance, exchange: string): string {
  const key = `exchanges.${exchange}`;
  return i18n.exists(key) ? t(key) : exchange.charAt(0).toUpperCase() + exchange.slice(1);
}
