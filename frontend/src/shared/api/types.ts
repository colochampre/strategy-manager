/**
 * Mirrors `reconciliation/infrastructure/router.py`'s response models. Every
 * money field is typed `string` on purpose — the backend serializes
 * `Decimal` values as JSON strings (never `Decimal`/`float`) so an
 * append-only ledger never loses precision on the wire. Nothing in this
 * module (or anything importing it in this unit) converts a money field
 * with `Number`/`parseFloat`.
 */

export interface ProposedFill {
  exchange_fill_id: string;
  exchange_order_id: string | null;
  side: string;
  quantity: string;
  price: string;
  fee: string;
  fee_currency: string;
  filled_at: string;
}

/** Mirrors `BookingProposalView` — the frozen snapshot in full. */
export interface BookingProposal {
  id: string;
  discrepancy_id: string;
  exchange: string;
  venue: string;
  settlement_currency: string;
  symbol: string;
  kind: string;
  allocation_id: string;
  strategy_id: string;
  side: string;
  quantity: string;
  observed_venue_net_base: string;
  observed_ledger_net_base: string;
  observed_allocation_ids: readonly string[];
  fills: readonly ProposedFill[];
  client_order_id: string;
  expires_at: string;
  prepared_by_job_id: string;
  created_at: string;
  state: string;
  decided_at: string | null;
  decided_by: string | null;
  decision_reason: string | null;
  execution_attempt_id: string | null;
}

export interface ApproveResponse {
  outcome: string;
  execution_attempt_id: string | null;
  ledger_entries_written: number;
}

export interface RejectResponse {
  outcome: string;
  reason: string | null;
}

/** The flat `{outcome, detail}` shape every 409/422/503 refusal returns. */
export interface RefusalBody {
  outcome: string;
  detail: string;
}
