import { useTranslation } from "react-i18next";

import { exchangeName } from "@/shared/exchanges/exchange-name";

interface PoolEyebrowProps {
  exchange: string;
  venue: string;
  /** The pool's settlement currency. */
  currency: string;
  /** The exchange has this one pool only: the prototype says "single pool" instead of naming the venue. */
  sole?: boolean;
}

/**
 * The line under the header card's label (ex1 `.hc-sub`): the exchange by its display name (task 7p.1, owner
 * decision 77) and the pool, in the settlement currency. Two pools of one exchange stay apart by their venue, the
 * API's identifier; a sole pool needs no venue.
 */
export function PoolEyebrow({ exchange, venue, currency, sole = false }: PoolEyebrowProps) {
  const { t, i18n } = useTranslation();
  const name = exchangeName(t, i18n, exchange);
  return (
    <p data-testid="pool-eyebrow" className="mt-0.5 text-[13px] text-ink-3">
      {sole ? t("overview.header.poolSole", { exchange: name, currency }) : t("overview.header.pool", { exchange: name, venue, currency })}
    </p>
  );
}
