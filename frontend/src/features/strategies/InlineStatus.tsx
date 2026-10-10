import { cn } from "@/shared/lib/cn";

export type InlineStatusTone = "neutral" | "failure";

interface InlineStatusProps {
  /** What happened, already translated; `null` while there is nothing to say. */
  message: string | null;
  /**
   * `neutral` is only announced: the control already shows the news (a button's own text), so the region is
   * visually hidden. `failure` is a visible text in the loss colour, because a control that merely stopped
   * saying "Copied" would not say that nothing was copied.
   */
  tone?: InlineStatusTone;
}

/**
 * What a control tells a screen reader, and a failure it also shows ("Saved", "Copied", "Could not copy"). It
 * is ALWAYS mounted and empty until it has something to say, because a live region that appears together with
 * its text is not reliably announced. Presentational: the control that owns the state decides what it says
 * and when.
 */
export function InlineStatus({ message, tone = "neutral" }: InlineStatusProps) {
  return (
    <span
      role="status"
      aria-live="polite"
      className={cn("text-sm", tone === "failure" ? "text-loss" : "sr-only text-ink-2")}
    >
      {message}
    </span>
  );
}
