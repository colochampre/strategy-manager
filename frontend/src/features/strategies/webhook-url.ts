const WEBHOOK_PATH = "/webhook/tradingview";

/**
 * The webhook URL: plain concatenation of a checked origin, a constant path and `value`, which is the
 * translated placeholder or the percent-encoded secret, already prepared by the caller. With no origin
 * (null, or an empty text) it is the path alone, so `null` is never written into it.
 */
export function webhookUrl(origin: string | null, value: string): string {
  return `${origin ?? ""}${WEBHOOK_PATH}?secret=${value}`;
}
