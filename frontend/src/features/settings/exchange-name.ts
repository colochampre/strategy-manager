import type { TFunction, i18n as I18nInstance } from "i18next";

/** The exchange's proper name from `exchanges.<id>`; an id with no entry is shown as the API spells it. */
export function exchangeName(t: TFunction, i18n: I18nInstance, exchange: string): string {
  const key = `exchanges.${exchange}`;
  return i18n.exists(key) ? t(key) : exchange;
}
