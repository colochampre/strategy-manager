import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useHiddenStore } from "@/shared/hidden/hidden-store";

/** What a hidden amount reads (ex2). */
export const MASK = "******";

/** Whether the panel is hiding the user's money right now. */
export function useHidden(): boolean {
  return useHiddenStore((state) => state.hidden);
}

/** A note that only restates a hidden figure (how much of a position was opened): drawn while shown, left out while hidden. */
export function Revealed({ children }: { children: ReactNode }) {
  return useHidden() ? null : <>{children}</>;
}

/**
 * The one masking point: a money figure (a balance, a PnL in currency, a fee, a margin, a position's size) is drawn
 * through this, so that every page hides it together. Percentages, prices and counts are not. The stars are in the
 * prototype's mono face and take the figure's size; they are an image named "Hidden", so a screen reader hears the
 * word and not "asterisk" six times.
 */
export function Masked({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const hidden = useHidden();
  if (!hidden) return <>{children}</>;
  return (
    <span role="img" aria-label={t("hidden.label")} className="font-mono tracking-[0.08em] text-ink-2">
      {MASK}
    </span>
  );
}
