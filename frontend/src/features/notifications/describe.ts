import { ArrowLeftRight, Gauge, Info, KeyRound, Shield, ShieldAlert, TriangleAlert, User } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { TFunction, i18n as I18nInstance } from "i18next";

import type { NotificationItem, NotificationKind } from "@/shared/api/notifications";
import { exchangeName } from "@/shared/exchanges/exchange-name";
import { amountText, parseDecimal, toneClass } from "@/shared/lib/amount-text";
import { tableFigureText } from "@/shared/lib/figure-text";

/** One sentence of an item: an i18n key under `notifications.sentence` and what it interpolates. */
export interface SentencePart {
  key: string;
  values: Record<string, string>;
  /** The class of the result's figure, for the one part that carries a PnL. */
  pnlTone?: string;
}

export interface Description {
  icon: LucideIcon;
  /** The class of the icon when it is not the kind's own colour (the manual close's grey person). */
  iconTone: string | null;
  titleKey: string;
  titleValues: Record<string, string>;
  sentence: SentencePart[];
  /** Where the item sends the user to fix it, if anywhere. */
  link: { to: string; labelKey: string } | null;
}

const CLOSE_CAUSES: readonly string[] = [
  "SIGNAL",
  "MANUAL_CLOSE",
  "STOP_FIRED",
  "STOP_FAILED_CLOSED",
  "STRATEGY_STOPPED_CLOSED",
];

const REFUSAL_REASONS: readonly string[] = [
  "OPENING_REFUSED_LEVERAGE_CAP",
  "OPENING_REFUSED_ACCOUNT_SUSPENDED",
  "OPENING_REFUSED_AUTHOR_SUSPENDED",
  "EXCHANGE_KEY_READ_ONLY",
  "EXCHANGE_HAS_NO_KEY",
  "MARGIN_NOT_ISOLATED",
  "LEVERAGE_CONFLICT",
  "LEVERAGE_NOT_APPLIED",
];

/** The reasons whose fix is a key: they link to where the keys are managed. */
const KEY_REASONS: readonly string[] = ["EXCHANGE_KEY_READ_ONLY", "EXCHANGE_HAS_NO_KEY"];

const CLOSE_ICONS: Readonly<Record<string, LucideIcon>> = {
  STOP_FIRED: Shield,
  STOP_FAILED_CLOSED: ShieldAlert,
  STRATEGY_STOPPED_CLOSED: ShieldAlert,
};

const KIND_ICONS: Readonly<Record<NotificationKind, LucideIcon>> = {
  OPERATION: ArrowLeftRight,
  SAFETY: Shield,
  NOTICE: KeyRound,
  DISCREPANCY: TriangleAlert,
};

/**
 * What an item says: its icon, title, sentence and link, from its event, its reason and its close cause. A value this
 * build does not know falls to a generic line (never a blank), and a missing field is written as a dash or a plain
 * word, never as "null".
 */
export function describeItem(item: NotificationItem, t: TFunction, i18n: I18nInstance, locale: string): Description {
  const dash = t("trades.noValue");
  const exchange = item.exchange === null ? t("notifications.unknownExchange") : exchangeName(t, i18n, item.exchange);
  const strategy = item.strategy_name ?? t("notifications.unknownStrategy");
  const pair = item.pair ?? dash;
  const side = item.side === null ? t("notifications.unknownSide") : t(`positions.table.sideWord.${item.side}`);
  const currency = item.currency ?? "";
  const figure = (value: string | null) => (value === null ? dash : (tableFigureText(value) ?? dash));
  const base = { icon: KIND_ICONS[item.kind], iconTone: null, link: null };

  if (item.event === "OPENED") {
    const values = { side, pair, exchange, entry: figure(item.entry_price), currency };
    const sentence: SentencePart[] =
      item.leverage === null
        ? [{ key: "OPENED", values }]
        : [{ key: "OPENED_LEVERAGE", values: { ...values, leverage: figure(item.leverage) } }];
    return {
      ...base,
      titleKey: "OPENED",
      titleValues: { strategy },
      sentence,
    };
  }

  if (item.event === "CLOSED") {
    const cause = item.close_cause !== null && CLOSE_CAUSES.includes(item.close_cause) ? item.close_cause : "SIGNAL";
    const sentence: SentencePart[] = [
      { key: `CLOSED_${cause}`, values: { side, pair, exchange, exit: figure(item.exit_price), currency } },
    ];
    const pnl = item.pnl === null ? null : parseDecimal(item.pnl);
    if (pnl !== null) {
      sentence.push({
        key: "result",
        values: { pnl: amountText(pnl, currency, locale, true), currency },
        pnlTone: toneClass(pnl),
      });
    }
    return {
      ...base,
      icon: cause === "MANUAL_CLOSE" ? User : (CLOSE_ICONS[cause] ?? base.icon),
      iconTone: cause === "MANUAL_CLOSE" ? "text-ink-3" : null,
      titleKey: `CLOSED_${cause}`,
      titleValues: { strategy },
      sentence,
    };
  }

  if (item.event === "OPENING_REFUSED") {
    const known = item.reason !== null && REFUSAL_REASONS.includes(item.reason);
    const detail = (name: string) => {
      const value = item.detail[name];
      return value === undefined ? dash : (tableFigureText(value) ?? value);
    };
    return {
      ...base,
      titleKey: "OPENING_REFUSED",
      titleValues: { strategy },
      sentence: [
        known && item.reason !== null
          ? {
              key: item.reason,
              values: { exchange, pair, requested: detail("requested_leverage"), max: detail("max_leverage") },
            }
          : { key: "openingRefused", values: {} },
      ],
      link:
        item.reason !== null && KEY_REASONS.includes(item.reason)
          ? { to: "/exchanges", labelKey: "nav.exchanges" }
          : null,
    };
  }

  // A seat lowered to the cap of its strategy's wider stop (RD.9): no market, no figure, only the two leverages.
  if (item.event === "LEVERAGE_LOWERED") {
    const leverage = (name: string) => {
      const value = item.detail[name];
      return value === undefined ? dash : (tableFigureText(value) ?? value);
    };
    return {
      ...base,
      icon: Gauge,
      titleKey: "LEVERAGE_LOWERED",
      titleValues: { strategy },
      sentence: [{ key: "LEVERAGE_LOWERED", values: { strategy, from: leverage("from"), to: leverage("to") } }],
    };
  }

  if (item.event === "DISCREPANCY") {
    const known = item.reason === "NO_MATCHING_ALLOCATION";
    return {
      ...base,
      titleKey: known ? "DISCREPANCY_NO_MATCHING_ALLOCATION" : "DISCREPANCY",
      titleValues: { exchange },
      sentence: [known ? { key: "DISCREPANCY_NO_MATCHING_ALLOCATION", values: { pair } } : { key: "discrepancy", values: {} }],
      link: { to: "/discrepancies", labelKey: "notifications.review" },
    };
  }

  return { ...base, icon: Info, titleKey: "unknown", titleValues: {}, sentence: [{ key: "unknown", values: {} }] };
}
