import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { amountText, parseDecimal, percentText, toneClass } from "@/features/overview/format";
import type { RangeName } from "@/features/overview/RangeSelector";
import { cn } from "@/shared/lib/cn";

const DASH = "—";

interface LedgerLineProps {
  /** The pool's settlement currency; every figure is in it. */
  currency: string;
  /** `balance.available` from `GET /pools`; null while nothing has synced. Left out, the line has no balance pair. */
  available?: string | null;
  /** Which range summary `pnl` and `ret` belong to. */
  range: RangeName;
  /** The range's `pnl`, money. */
  pnl: string;
  /** The range's `return`, a ratio; null renders an em dash, never a zero. */
  ret: string | null;
  /** The pool's all-time `max_drawdown`, a ratio at most zero. */
  maxDrawdown: string;
  /** Replaces the return's label (already translated, range included), for a figure that is not the pool's own return. */
  returnLabel?: string;
}

interface PairProps {
  children: ReactNode;
  /** A separator follows the pair; it stays inside it, so it never starts a line. */
  separator?: boolean;
}

/**
 * One label with its value. From `lg` up the pair never breaks inside (a value
 * stranded from its label reads as another figure, worst with eight-decimal
 * BTC); the line wraps only BETWEEN pairs. Below `lg` a pair may break like any
 * text: one that cannot is wider than a small screen and overflows it sideways.
 */
function Pair({ children, separator = false }: PairProps) {
  return (
    <span data-testid="ledger-pair" className="lg:whitespace-nowrap">
      {children}
      {separator && (
        <span aria-hidden="true" className="text-rule">
          {" · "}
        </span>
      )}
    </span>
  );
}

/**
 * One pool's headline: the available balance as the lead figure, then the
 * range's PnL and return and the deepest drawdown, as four label and value pairs
 * that, from `lg` up, wrap only between one another. Figures are parsed only to be
 * formatted; nothing is computed (CLAUDE.md, rule 7).
 */
export function LedgerLine({ currency, available, range, pnl, ret, maxDrawdown, returnLabel }: LedgerLineProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? "en";

  // Omitted is a line with no balance at all (one strategy's); null is a balance nothing has synced yet.
  const hasBalance = available !== undefined;
  const availableValue = available === undefined || available === null ? null : parseDecimal(available);
  const pnlValue = parseDecimal(pnl);
  const returnValue = ret === null ? null : parseDecimal(ret);
  const drawdownValue = parseDecimal(maxDrawdown);

  if (
    (available !== undefined && available !== null && availableValue === null) ||
    pnlValue === null ||
    (ret !== null && returnValue === null) ||
    drawdownValue === null
  ) {
    return (
      <p role="alert" data-testid="ledger-line" className="text-sm text-loss">
        {t("overview.ledger.unreadable")}
      </p>
    );
  }

  const rangeLabel = t(`overview.range.${range}`);

  return (
    <p
      data-testid="ledger-line"
      className="font-mono text-[15px] leading-normal text-ink-2 tabular-nums"
    >
      {hasBalance && (
        <Pair separator>
          <span data-testid="ledger-lead" className="text-[26px] font-semibold leading-none text-ink">
            {availableValue === null ? DASH : amountText(availableValue, currency, locale)}
          </span>{" "}
          {t("overview.ledger.available", { currency })}
        </Pair>
      )}
      <Pair separator>
        {t("overview.ledger.pnl", { range: rangeLabel })}{" "}
        <span
          data-testid="ledger-pnl"
          className={cn("font-semibold", toneClass(pnlValue), !hasBalance && "text-[26px] leading-none")}
        >
          {amountText(pnlValue, currency, locale, true)}
        </span>
      </Pair>
      <Pair separator>
        {returnLabel ?? t("overview.ledger.return", { range: rangeLabel })}{" "}
        <span
          data-testid="ledger-return"
          className={cn("font-semibold", returnValue !== null && toneClass(returnValue))}
        >
          {returnValue === null ? DASH : percentText(returnValue, locale)}
        </span>
      </Pair>
      <Pair>
        {t("overview.ledger.deepest")}{" "}
        <span data-testid="ledger-deepest" className="font-semibold text-loss">
          {percentText(drawdownValue, locale)}
        </span>
      </Pair>
    </p>
  );
}
