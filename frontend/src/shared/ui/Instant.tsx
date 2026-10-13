import { clockText, compactDateText } from "@/shared/lib/figure-text";

/**
 * An Opened or Closed instant on two lines (owner decision 46): the numeric UTC date in the panel's
 * language, then the 24-hour UTC time in ink-3. An instant that cannot be read shows as the server
 * wrote it, with no time line.
 */
export function Instant({ iso, locale }: { iso: string; locale: string }) {
  const time = clockText(iso);
  return (
    <>
      <span className="block">{compactDateText(iso, locale)}</span>
      {time !== null && <span className="block text-ink-3">{time}</span>}
    </>
  );
}
