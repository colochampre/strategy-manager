import { useId } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { StrategyLink } from "@/features/discrepancies/StrategyLink";
import { baseCurrencyOf, netDifference, quantityText, signedQuantityText } from "@/features/discrepancies/figures";
import type { ConfirmedDiscrepancy } from "@/shared/api/discrepancies";
import { cn } from "@/shared/lib/cn";
import { clockText, compactDateText, timeOfAnswerText } from "@/shared/lib/figure-text";

export type DiscrepancyVariant = "needsYou" | "beingBooked";

interface DiscrepancyItemProps {
  item: ConfirmedDiscrepancy;
  variant: DiscrepancyVariant;
  /** The `read_at` of the answer the item belongs to: a time on another UTC day is written with its date. */
  readAt: string;
}

type Translate = ReturnType<typeof useTranslation>["t"];

interface Sentences {
  /** What is said where the item puts its headline: red on a Needs-you item, neutral on one being booked. */
  headline: string;
  /** The kind in words, when the headline is not already it. */
  kind: string | null;
}

/**
 * The headline and the kind of an item. A Needs-you item says its reason when the reason is a sentence of its
 * own (`NOT_BOOKED` keeps the kind under it; `SEVERAL_ALLOCATIONS` is the whole story). Every other reason
 * (`NOT_BOOKABLE`, `REASON_UNKNOWN`, none) has no sentence of its own, so the kind is the headline: an item is
 * never left without words. An item being booked ignores its reason, and says it is being booked.
 */
function sentencesOf(item: ConfirmedDiscrepancy, variant: DiscrepancyVariant, t: Translate): Sentences {
  const kind = t(`discrepancies.kind.${item.kind}`);
  if (variant === "beingBooked") return { headline: t("discrepancies.beingBooked"), kind };
  if (item.reason === "NOT_BOOKED") return { headline: t("discrepancies.reason.NOT_BOOKED"), kind };
  if (item.reason === "SEVERAL_ALLOCATIONS") return { headline: t("discrepancies.reason.SEVERAL_ALLOCATIONS"), kind: null };
  return { headline: kind, kind: null };
}

interface FactProps {
  label: string;
  className?: string | undefined;
  children: ReactNode;
}

function Fact({ label, className, children }: FactProps) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-0.5", className)}>
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className="min-w-0 text-sm text-ink">{children}</dd>
    </div>
  );
}

interface NetProps {
  label: string;
  value: string;
  unit: string | null;
  className?: string | undefined;
}

function Net({ label, value, unit, className }: NetProps) {
  return (
    <Fact label={label} className={className}>
      <span className="font-mono tabular-nums">
        {value}
        {unit !== null && (
          <>
            {" "}
            <span className="text-xs text-ink-3">{unit}</span>
          </>
        )}
      </span>
    </Fact>
  );
}

/**
 * One confirmed discrepancy (owner decision 66; prototype examples 5, 6, 8c, 10 and 11): the pair and its pool,
 * what is wrong in words, both nets and their signed difference, the strategies involved, when it was confirmed
 * and last compared, whose discrepancy it is (multi-user AD10), and what the owner can do.
 *
 * A Needs-you item has a red border and a red headline: the words are the signal, the colour only follows them
 * (decision 65). An item being booked is neutral, says so, and offers nothing to do: nothing needs the owner.
 * The id is the one a link to the item names (`#discrepancy-<id>`).
 */
export function DiscrepancyItem({ item, variant, readAt }: DiscrepancyItemProps) {
  const { t, i18n } = useTranslation();
  const titleId = useId();
  const locale = i18n.resolvedLanguage ?? "en";
  const calm = variant === "beingBooked";
  const { headline, kind } = sentencesOf(item, variant, t);
  const unit = baseCurrencyOf(item.symbol, item.settlement_currency);
  const difference = netDifference(item.venue_net_base, item.ledger_net_base);
  const confirmedTime =
    item.confirmed_at === null
      ? null
      : `${compactDateText(item.confirmed_at, locale)} ${clockText(item.confirmed_at) ?? ""}`.trim();
  const lastCompared = timeOfAnswerText(item.last_observed_at, readAt, locale, true) ?? item.last_observed_at;

  return (
    <article
      id={`discrepancy-${item.discrepancy_id}`}
      aria-labelledby={titleId}
      className={cn("flex min-w-0 flex-col gap-3 rounded-lg border bg-panel p-4", calm ? "border-rule" : "border-loss")}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h4 id={titleId} className="font-mono text-base font-semibold text-ink">
          {item.symbol}
        </h4>
        <span className="font-mono text-xs text-ink-3">
          {item.venue} · {item.settlement_currency}
        </span>
      </div>
      <div className="flex flex-col gap-1">
        <p className={cn("text-sm font-medium", calm ? "text-ink-2" : "text-loss")}>{headline}</p>
        {kind !== null && <p className="text-sm text-ink-2">{kind}</p>}
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
        <Net label={t("discrepancies.label.exchange")} value={quantityText(item.venue_net_base, locale)} unit={unit} />
        <Net label={t("discrepancies.label.ledger")} value={quantityText(item.ledger_net_base, locale)} unit={unit} />
        <Net
          label={t("discrepancies.label.difference")}
          value={difference === null ? "" : signedQuantityText(difference, locale)}
          unit={difference === null ? null : unit}
          className="col-span-2 sm:col-span-1"
        />
      </dl>
      <dl className="flex flex-wrap gap-x-8 gap-y-3">
        <Fact label={t(item.allocations.length > 1 ? "discrepancies.label.strategies" : "discrepancies.label.strategy")}>
          {item.allocations.length === 0
            ? t("discrepancies.label.noStrategy")
            : item.allocations.map((allocation, index) => (
                <span key={allocation.allocation_id}>
                  {index > 0 && ", "}
                  <StrategyLink id={allocation.strategy_id} name={allocation.strategy_name} />
                </span>
              ))}
        </Fact>
        {confirmedTime !== null && (
          <Fact label={t("discrepancies.label.confirmed")}>
            <span className="font-mono text-xs">{t("discrepancies.read.time", { time: confirmedTime })}</span>
          </Fact>
        )}
        <Fact label={t("discrepancies.label.lastCompared")}>
          <span className="font-mono text-xs">{t("discrepancies.read.time", { time: lastCompared })}</span>
        </Fact>
        <Fact label={t("discrepancies.label.user")}>
          <span className="break-all">{item.user_email}</span>
        </Fact>
      </dl>
      {!calm && (
        <dl className="flex flex-col gap-0.5">
          <dt className="text-xs text-ink-3">{t("discrepancies.label.whatYouCanDo")}</dt>
          <dd className="text-sm text-ink-2">
            {t(item.kind === "NO_MATCHING_ALLOCATION" ? "discrepancies.action.byHand" : "discrepancies.action.manual")}
          </dd>
        </dl>
      )}
    </article>
  );
}
