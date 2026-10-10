import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { cutAmountText } from "@/features/strategies/format";

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

export function ShareAmount({ view, trailing }: ShareAmountProps) {
  const { t, i18n } = useTranslation();
  const known = view.kind === "known" ? cutAmountText(view.amount, view.currency, i18n.language) : null;
  return (
    <div className="flex items-center">
      <p className="text-sm text-ink">
        {view.kind === "known" ? t("strategies.detail.share.amount", { amount: known, currency: view.currency }) : null}
      </p>
      {trailing}
    </div>
  );
}
