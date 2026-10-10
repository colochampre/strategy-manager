import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { clockText, cutAmountText } from "@/features/strategies/format";
import { cn } from "@/shared/lib/cn";

/** A figure the server served for the value in the field. `staleAt` is the balance's read time when stale. */
export interface KnownAmount {
  kind: "known";
  /** The served amount, a plain decimal string. */
  amount: string;
  currency: string;
  staleAt: string | null;
}

/** What the line under the track says: a figure, or why there is none. */
export type ShareAmountView = KnownAmount | { kind: "loading" | "noBalance" | "failed" | "none" };

interface ShareAmountProps {
  view: ShareAmountView;
  /** The amount's information button, at the end of the row; the row is there in every state. */
  trailing?: ReactNode;
}

/** The mark for an absent figure, as the panel's tables write it. */
const DASH = "—";

/**
 * The line under the track (design § C2). Presentational: it writes strings the server served and reads
 * no pool, so it cannot multiply a balance. The figure is cut down as text to the currency's decimals;
 * a served amount that is not a plain decimal is a failed read, never "NaN".
 */
export function ShareAmount({ view, trailing }: ShareAmountProps) {
  const { t, i18n } = useTranslation();
  const known = view.kind === "known" ? cutAmountText(view.amount, view.currency, i18n.language) : null;
  const figure = view.kind === "known" && known !== null;

  let line: string;
  if (view.kind === "known") {
    line = known === null ? t("strategies.detail.share.amountError") : t("strategies.detail.share.amount", { amount: known, currency: view.currency });
  } else if (view.kind === "loading") {
    line = t("strategies.detail.share.amountLoading");
  } else if (view.kind === "noBalance") {
    line = t("strategies.detail.share.amountNoBalance");
  } else if (view.kind === "failed") {
    line = t("strategies.detail.share.amountError");
  } else {
    line = DASH;
  }

  const staleAt = view.kind === "known" && figure ? view.staleAt : null;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-start">
        <p className={cn("text-sm", figure ? "text-ink" : "text-ink-2")}>{line}</p>
        {trailing}
      </div>
      {staleAt !== null && (
        <p className="text-xs text-ink-2">
          {t("strategies.detail.share.amountStale", { time: clockText(staleAt) ?? staleAt })}
        </p>
      )}
    </div>
  );
}
