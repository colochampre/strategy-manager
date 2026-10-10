const WEBHOOK_PATH = "/webhook/tradingview";

/** STUB (12f.10.8 RED): the path alone, until the GREEN puts the checked origin in front of it. */
export function webhookUrl(_origin: string | null, value: string): string {
  return `${WEBHOOK_PATH}?secret=${value}`;
}
