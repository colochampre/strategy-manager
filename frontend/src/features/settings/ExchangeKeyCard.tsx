import type { CredentialEntry } from "@/shared/api/credentials";

export interface ExchangeKeyCardProps {
  /** The exchange's id as the API spells it. */
  exchange: string;
  /** Its row of `GET /credentials`, or `undefined` when it is not listed. */
  entry: CredentialEntry | undefined;
  /** Whether a pool of this exchange is enabled: `null` while that is not known. */
  poolOn: boolean | null;
  /** Whether the panel manages a key for this exchange (it is in `served-exchanges.json`). */
  served: boolean;
}

/** STUB (RED): prints `trades` and `no withdrawal` for every stored key and nothing else. */
export function ExchangeKeyCard({ exchange, entry }: ExchangeKeyCardProps) {
  return (
    <article>
      <h3>{exchange}</h3>
      {entry?.status === "STORED" && (
        <ul>
          <li>trades</li>
          <li>no withdrawal</li>
        </ul>
      )}
    </article>
  );
}
