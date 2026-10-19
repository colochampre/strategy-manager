import { useTranslation } from "react-i18next";

import { exchangeName } from "@/shared/exchanges/exchange-name";

interface PoolEyebrowProps {
  exchange: string;
  venue: string;
  /** The pool's settlement currency. */
  currency: string;
}

/**
 * `{EXCHANGE} · {VENUE} · {CCY}`. The exchange is its display name (task 7p.1, owner decision 77), the venue
 * and the currency are the API's identifiers, and the style upper-cases all three.
 */
export function PoolEyebrow({ exchange, venue, currency }: PoolEyebrowProps) {
  const { t, i18n } = useTranslation();
  return (
    <p
      data-testid="pool-eyebrow"
      className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-3"
    >
      {`${exchangeName(t, i18n, exchange)} · ${venue} · ${currency}`}
    </p>
  );
}
