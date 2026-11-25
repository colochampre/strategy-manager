import type { ReactNode } from "react";

import { cn } from "@/shared/lib/cn";

/**
 * The prototype's `.pill` (ex6, ex7): 24 px tall, a 12 px radius, 12 px medium text, a 1 px edge of the tone at about
 * 40 % and a soft fill of the same tone. The tones are the notification tokens' `notif-operation` (gain) and
 * `notif-notice` (ink-2). The amber one is `KeyMark`'s own, because amber means "needs your decision" and only the
 * components the design names may draw it.
 */
export const PILL = "inline-flex h-6 items-center gap-1.5 rounded-xl border px-2.5 text-xs font-medium whitespace-nowrap";

export type PillTone = "gain" | "neutral";

export const PILL_TONE: Record<PillTone, { pill: string; dot: string }> = {
  gain: { pill: "border-gain/40 bg-gain/14 text-gain-bright", dot: "bg-gain" },
  neutral: { pill: "border-ink-2/40 bg-ink-2/11 text-ink-2", dot: "bg-ink-2" },
};

/** The pill's dot, 6 px, in the tone's edge colour. */
export function PillDot({ className }: { className: string }) {
  return <i data-dot="true" aria-hidden="true" className={cn("size-1.5 shrink-0 rounded-full", className)} />;
}

export function Pill({ tone, dot = false, children }: { tone: PillTone; dot?: boolean; children: ReactNode }) {
  return (
    <span className={cn(PILL, PILL_TONE[tone].pill)}>
      {dot && <PillDot className={PILL_TONE[tone].dot} />}
      {children}
    </span>
  );
}
