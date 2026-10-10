interface InlineStatusProps {
  /** What happened, already translated; `null` while there is nothing to say. */
  message: string | null;
  /** `failure` is the loss colour; the default is neutral ink. */
  tone?: "neutral" | "failure";
}

/** STUB (12f.10.11 RED): a bare span with no role, until the GREEN makes it a live region. */
export function InlineStatus({ message }: InlineStatusProps) {
  return <span>{message}</span>;
}
