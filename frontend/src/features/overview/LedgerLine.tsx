import { Coins, TrendingDown, Wallet } from "lucide-react";
import { useTranslation } from "react-i18next";

import { money, percent, STATS_GRID, StatGroup } from "@/features/strategies/StrategyCard";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";
import { parseDecimal, toneClass } from "@/shared/lib/amount-text";
import type { RangeName } from "@/features/overview/RangeSelector";

interface LedgerLineProps {
  /** The pool's settlement currency; every figure is in it. */
  currency: string;
  /** `balance.available` from `GET /pools`; null while nothing has synced. Left out, the line has no balance figure. */
  available?: string | null;
  /** Which range summary `pnl` and `ret` belong to. */
  range: RangeName;
  /** The range's `pnl`, money. */
  pnl: string;
  /** The range's `return`, a ratio; null renders an em dash, never a zero. */
  ret: string | null;
  /** The pool's all-time `max_drawdown`, a ratio at most zero. */
  maxDrawdown: string;
  /** A note about the balance, behind an (i) right of it: the button's name and the text it opens. */
  availableInfo?: { label: string; text: string } | undefined;
}

/**
 * One pool's headline in the strategy pages' groups (owner, 2026-11-17): an icon and a title over each group's
 * values, the available balance, the range's PnL with its return, and the deepest drawdown, each unit joined to its
 * figure and smaller. Figures are parsed only to be formatted; nothing is computed (CLAUDE.md, rule 7).
 */
export function LedgerLine({
  currency,
  available,
  range,
  pnl,
  ret,
  maxDrawdown,
  availableInfo,
}: LedgerLineProps) {
  const { t, i18n } = useTranslation();
  const disclosure = useInfoDisclosure();
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

  const returnFigure = percent(returnValue, locale);
  const deepest = percent(drawdownValue, locale);
  const pnlTitle =
    range === "All" ? t("strategies.card.totalPnl") : t("strategies.card.totalPnlRange", { range: t(`overview.range.${range}`) });

  return (
    <>
      <dl data-testid="ledger-line" className={STATS_GRID}>
        {hasBalance && (
          <StatGroup
            testId="ledger-group-available"
            icon={Wallet}
            label={t("overview.ledger.available")}
            info={availableInfo === undefined ? undefined : <InfoButton disclosure={disclosure} label={availableInfo.label} />}
          >
            <span data-testid="ledger-lead">{money(availableValue, currency, locale)}</span>
          </StatGroup>
        )}
        <StatGroup testId="ledger-group-pnl" icon={Coins} label={pnlTitle}>
          <span data-testid="ledger-pnl" className={toneClass(pnlValue)}>
            {money(pnlValue, currency, locale, true)}
          </span>
          <span data-testid="ledger-return" className={returnFigure.tone}>
            {returnFigure.value}
          </span>
        </StatGroup>
        <StatGroup testId="ledger-group-drawdown" icon={TrendingDown} label={t("strategies.card.maxDrawdown")}>
          <span data-testid="ledger-deepest" className="text-loss">
            {deepest.value}
          </span>
        </StatGroup>
      </dl>
      {availableInfo !== undefined && (
        <InfoText disclosure={disclosure}>
          <p data-testid="balance-stale" className="font-mono text-[11px] text-ink-2">
            {availableInfo.text}
          </p>
        </InfoText>
      )}
    </>
  );
}
