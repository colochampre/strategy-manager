import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ageParts, ageText } from "@/features/strategies/age-text";
import type { PublicStrategy } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import { IconTip } from "@/shared/ui/Tooltip";

/** What a figure shows when there is nothing true to say yet. */
const NO_FIGURE = "—";

interface FigureProps {
  label: string;
  testId: string;
  value: string;
  tone?: string | undefined;
  info?: ReactNode;
  /** Drawn in place of the label, which then names it and explains it on hover. */
  icon?: LucideIcon;
  /** Added to the value's classes, last, for a lead figure that is larger or must not break. */
  valueClassName?: string;
  /** The icon left of the value instead of above it: for a lead figure, whose larger value the icon would not line up over. */
  inline?: boolean;
  /** Drawn right of the value, inside it: an information button about the figure. */
  after?: ReactNode;
}

/** One figure: its label, or its icon, centred over its value. */
export function Figure({
  label,
  testId,
  value,
  tone = "text-ink",
  info,
  icon,
  valueClassName,
  inline = false,
  after,
}: FigureProps) {
  return (
    // The label takes the room left, so a label that wraps never lowers its figure below the others in the row.
    <div
      className={cn(
        "flex w-fit",
        inline ? "flex-row items-center gap-2" : "flex-col items-center justify-between gap-0.5",
      )}
    >
      {/* Lifted above a card's stretched link, so the icon still answers the pointer with its tooltip. */}
      <dt className="relative z-10 flex items-start text-xs text-ink-3">
        {icon === undefined ? label : <IconTip icon={icon} label={label} />}
        {info}
      </dt>
      <dd
        data-testid={testId}
        className={cn(
          "font-mono text-sm lg:whitespace-nowrap",
          after !== undefined && "inline-flex items-center",
          tone,
          valueClassName,
        )}
      >
        {value}
        {after}
      </dd>
    </div>
  );
}

/** The time since an instant, short ("6d", "4mo 12d", "1y 4mo"), or a dash for an instant that cannot be read. */
export function useAgeSince(since: string | null): string {
  const { t } = useTranslation();
  const from = since === null ? Number.NaN : Date.parse(since);
  return Number.isNaN(from) ? NO_FIGURE : ageText(t, ageParts(new Date(from), new Date()));
}

/** Who wrote a strategy and the market it trades: what names it beside its name, on the list and on its page. */
export function PublicOrigin({ strategy }: { strategy: PublicStrategy }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-0.5">
      <p data-testid="public-origin" className="text-xs text-ink-2">
        {t("strategies.public.by", { name: strategy.author_name })}
      </p>
      <p data-testid="public-market" className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-3">
        {`${strategy.exchange} · ${strategy.venue} · ${strategy.settlement_currency}`}
      </p>
    </div>
  );
}
