interface PoolEyebrowProps {
  exchange: string;
  venue: string;
  /** The pool's settlement currency. */
  currency: string;
}

/**
 * `{EXCHANGE} · {VENUE} · {CCY}`. The text is the raw identifier the API uses;
 * capitalised display names are a separate polish (task 7p.1), and the style
 * upper-cases it.
 */
export function PoolEyebrow({ exchange, venue, currency }: PoolEyebrowProps) {
  return (
    <p
      data-testid="pool-eyebrow"
      className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-3"
    >
      {`${exchange} · ${venue} · ${currency}`}
    </p>
  );
}
