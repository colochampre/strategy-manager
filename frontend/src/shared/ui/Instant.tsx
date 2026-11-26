import { clockText, compactDateText } from "@/shared/lib/figure-text";

/**
 * An Opened or Closed instant on one line, as the prototype's tables write it (L30): the numeric UTC date in the
 * panel's language (owner decision 46), then the 24-hour UTC time in ink-3. An instant that cannot be read shows
 * as the server wrote it, with no time.
 */
export function Instant({ iso, locale }: { iso: string; locale: string }) {
  const time = clockText(iso);
  return (
    <>
      <span>{compactDateText(iso, locale)}</span>
      {time !== null && (
        <>
          {" "}
          <span className="text-ink-3">{time}</span>
        </>
      )}
    </>
  );
}
