import { Coins, TrendingDown, TrendingUp, Wallet } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { Figure } from "@/features/strategies/PublicFigures";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";
import { amountText, parseDecimal, percentText, toneClass } from "@/shared/lib/amount-text";
import type { RangeName } from "@/features/overview/RangeSelector";

const DASH = "—";

/**
 * A label that names the range only when the range narrows the figure: `base` for All, `${base}Range` (which
 * carries `{{range}}`) for 7D, 30D and the others. All is the whole history, so saying it adds nothing.
 */
export function rangeLabel(t: TFunction, base: string, range: RangeName): string {
  return range === "All" ? t(base) : t(`${base}Range`, { range: t(`overview.rangeLong.${range}`) });
}

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
  /** Replaces the return's tooltip (already translated, range included), for a figure that is not the pool's own return. */
  returnLabel?: string;
  /** A note about the balance, behind an (i) right of it: the button's name and the text it opens. */
  availableInfo?: { label: string; text: string } | undefined;
}

/** A value keeps to one line: a currency stranded from its number reads as another figure, worst with eight-decimal BTC. */
const VALUE = "whitespace-nowrap font-semibold";
const LEAD = "text-[26px] leading-none";

/**
 * One pool's headline: the available balance as the lead figure, then the range's PnL and return and the
 * deepest drawdown, each as the icon the strategy cards use over its value, with the words in the icon's tooltip.
 * Figures are parsed only to be formatted; nothing is computed (CLAUDE.md, rule 7).
 */
export function LedgerLine({
  currency,
  available,
  range,
  pnl,
  ret,
  maxDrawdown,
  returnLabel,
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

  return (
    <>
      <dl data-testid="ledger-line" className="tabular flex flex-wrap items-center gap-x-6 gap-y-3">
        {hasBalance && (
          // The balance is larger than the figures beside it, so its wallet sits left of it, not above.
          <Figure
            icon={Wallet}
            label={t("overview.ledger.available")}
            testId="ledger-lead"
            value={availableValue === null ? DASH : `${amountText(availableValue, currency, locale)} ${currency}`}
            valueClassName={`${VALUE} ${LEAD}`}
            inline
            after={
              availableInfo === undefined ? undefined : (
                <InfoButton disclosure={disclosure} label={availableInfo.label} />
              )
            }
          />
        )}
        {/* Without a balance the PnL is not a lead: it is the size of the return and the drawdown beside it. */}
        <Figure
          icon={Coins}
          label={rangeLabel(t, "overview.ledger.pnl", range)}
          testId="ledger-pnl"
          value={amountText(pnlValue, currency, locale, true)}
          tone={toneClass(pnlValue)}
          valueClassName={VALUE}
        />
        <Figure
          icon={TrendingUp}
          label={returnLabel ?? rangeLabel(t, "overview.ledger.return", range)}
          testId="ledger-return"
          value={returnValue === null ? DASH : percentText(returnValue, locale)}
          {...(returnValue === null ? {} : { tone: toneClass(returnValue) })}
          valueClassName={VALUE}
        />
        <Figure
          icon={TrendingDown}
          label={t("overview.ledger.deepest")}
          testId="ledger-deepest"
          value={percentText(drawdownValue, locale)}
          tone="text-loss"
          valueClassName={VALUE}
        />
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
