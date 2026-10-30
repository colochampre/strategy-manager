const WEBHOOK_PATH = "/webhook/tradingview";

/** What stands for the part of the secret that cannot be read back; the last four characters follow it. */
export const SECRET_MASK = "***";

/**
 * The webhook URL: plain concatenation of a checked origin, a constant path and `value`, which is the
 * mask or the percent-encoded secret, already prepared by the caller. With no origin
 * (null, or an empty text) it is the path alone, so `null` is never written into it.
 */
export function webhookUrl(origin: string | null, value: string): string {
  return `${origin ?? ""}${WEBHOOK_PATH}?secret=${value}`;
}
