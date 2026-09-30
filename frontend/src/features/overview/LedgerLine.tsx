import { useTranslation } from "react-i18next";

import { amountText, parseDecimal, percentText, toneClass } from "@/features/overview/format";
import type { RangeName } from "@/features/overview/RangeSelector";
import { cn } from "@/shared/lib/cn";

const DASH = "—";

interface LedgerLineProps {
  /** The pool's settlement currency; every figure is in it. */
  currency: string;
  /** `balance.available` from `GET /pools`; null while nothing has synced. */
  available: string | null;
  /** Which range summary `pnl` and `ret` belong to. */
  range: RangeName;
  /** The range's `pnl`, money. */
  pnl: string;
  /** The range's `return`, a ratio; null renders an em dash, never a zero. */
  ret: string | null;
  /** The pool's all-time `max_drawdown`, a ratio at most zero. */
  maxDrawdown: string;
}

function Separator() {
  return (
    <span aria-hidden="true" className="text-rule">
      {" · "}
    </span>
  );
}

/**
 * One pool's headline: the available balance as the lead figure, then the
 * range's PnL and return and the deepest drawdown. Figures are parsed only to be
 * formatted; nothing is computed (CLAUDE.md, rule 7).
 */
export function LedgerLine({ currency, available, range, pnl, ret, maxDrawdown }: LedgerLineProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? "en";

  const availableValue = available === null ? null : parseDecimal(available);
  const pnlValue = parseDecimal(pnl);
  const returnValue = ret === null ? null : parseDecimal(ret);
  const drawdownValue = parseDecimal(maxDrawdown);

  if (
    (available !== null && availableValue === null) ||
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
      className="font-mono text-[15px] leading-[1.7] text-ink-2 tabular-nums"
    >
      <span data-testid="ledger-lead" className="text-[26px] font-semibold text-ink">
        {availableValue === null ? DASH : amountText(availableValue, currency, locale)}
      </span>{" "}
      {t("overview.ledger.available", { currency })}
      <Separator />
      {t("overview.ledger.pnl", { range: rangeLabel })}{" "}
      <span data-testid="ledger-pnl" className={cn("font-semibold", toneClass(pnlValue))}>
        {amountText(pnlValue, currency, locale, true)}
      </span>
      <Separator />
      {t("overview.ledger.return", { range: rangeLabel })}{" "}
      <span
        data-testid="ledger-return"
        className={cn("font-semibold", returnValue !== null && toneClass(returnValue))}
      >
        {returnValue === null ? DASH : percentText(returnValue, locale)}
      </span>
      <Separator />
      {t("overview.ledger.deepest")}{" "}
      <span data-testid="ledger-deepest" className="font-semibold text-loss">
        {percentText(drawdownValue, locale)}
      </span>
    </p>
  );
}
