import { cn } from "@/shared/lib/cn";

interface InlineStatusProps {
  /** What happened, already translated; `null` while there is nothing to say. */
  message: string | null;
  /** `failure` is the loss colour; the default is neutral ink, never the gain colour. */
  tone?: "neutral" | "failure";
}

/**
 * A short confirmation or failure beside a control ("Saved", "Copied"). It is ALWAYS mounted and empty
 * until it has something to say, because a live region that appears together with its text is not
 * reliably announced. Presentational: the control that owns the state decides what it says and when.
 */
export function InlineStatus({ message, tone = "neutral" }: InlineStatusProps) {
  return (
    <span role="status" aria-live="polite" className={cn("text-sm", tone === "failure" ? "text-loss" : "text-ink-2")}>
      {message}
    </span>
  );
}
