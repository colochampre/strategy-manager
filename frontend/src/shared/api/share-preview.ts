import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";
import { type Entry, entryKey, entryParams, NO_ENTRY, useEntry } from "@/shared/api/entry";
import type { SharePreview } from "@/shared/api/types";

const STEP_COUNT = 100;
const PREVIEW_REFRESH_MS = 60_000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPool(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.exchange === "string" &&
    typeof value.venue === "string" &&
    typeof value.settlement_currency === "string"
  );
}

function isBalance(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.total === "string" &&
    typeof value.observed_at === "string" &&
    typeof value.stale === "boolean"
  );
}

/** The amount of the share as stored or asked: its share rides as a decimal string, like every money figure. */
function isExact(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.share === "string" &&
    typeof value.amount === "string" &&
    typeof value.below_pool_minimum === "boolean" &&
    // The notional rides only when a leverage was asked; an older server leaves it out, and null is the same.
    (value.notional === undefined || value.notional === null || typeof value.notional === "string")
  );
}

/** Step `position` (1 to 100) of the table: its share is a whole number equal to its place in the list. */
function isStep(value: unknown, position: number): boolean {
  return (
    isRecord(value) &&
    value.share === position &&
    typeof value.amount === "string" &&
    typeof value.below_pool_minimum === "boolean"
  );
}

/**
 * A body the panel can draw from: every field of the right type, and `balance`, `exact` and `steps` present
 * together (a hundred steps numbered 1 to 100 in order; `exact` may still be null) or absent together
 * (null, null, empty). A body that
 * fails is an error and never a partial table: an amount that was not served is never drawn.
 */
function isSharePreview(value: unknown): value is SharePreview {
  if (!isRecord(value)) return false;
  if (typeof value.strategy_id !== "string" || !isPool(value.pool)) return false;
  if (typeof value.currency !== "string" || typeof value.pool_minimum !== "string") return false;
  if (!Array.isArray(value.steps)) return false;
  if (value.balance === null) return value.exact === null && value.steps.length === 0;
  return (
    isBalance(value.balance) &&
    // `exact` is null too for a caller who holds no seat and asked no share (decision 39).
    (value.exact === null || isExact(value.exact)) &&
    value.steps.length === STEP_COUNT &&
    value.steps.every((step, index) => isStep(step, index + 1))
  );
}

/**
 * `GET /api/strategies/{id}/share-preview`: the amount of the stored share, or of `share` when one is
 * asked, plus the pool's hundred whole steps. READ-ONLY on the server; the panel multiplies nothing.
 */
export async function fetchSharePreview(
  strategyId: string,
  share?: string,
  leverage?: number,
  entry: Entry = NO_ENTRY,
): Promise<SharePreview> {
  const params: string[] = [];
  if (share !== undefined) params.push(`share=${encodeURIComponent(share)}`);
  // A whole number from 1 to 20 (the server's range); it asks for the notional beside the amount.
  if (leverage !== undefined) params.push(`leverage=${encodeURIComponent(String(leverage))}`);
  // A strategy off the list previews only for a reader who entered it by its link or a code.
  params.push(...entryParams(entry));
  const query = params.length === 0 ? "" : `?${params.join("&")}`;
  const body = await apiFetch<unknown>(`/strategies/${encodeURIComponent(strategyId)}/share-preview${query}`);
  if (!isSharePreview(body)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /strategies/{id}/share-preview: expected a share preview",
    });
  }
  return body;
}

/**
 * Query key `['strategy', id, 'share-preview']`, or `[..., 'share-preview', share]` for an asked share. It
 * sits under the strategy's own key, so a save, which invalidates that key, refreshes it. Read when the
 * control mounts and again every 60 s, the cadence of the balance.
 */
export function useSharePreview(strategyId: string, share?: string, leverage?: number) {
  const asked = share !== undefined || leverage !== undefined;
  const entry = useEntry();
  return useQuery({
    // An asked leverage is its own entry: the same share at another leverage has another notional.
    queryKey: [
      "strategy",
      strategyId,
      "share-preview",
      ...(asked ? [share ?? null] : []),
      ...(leverage === undefined ? [] : [{ leverage }]),
      ...entryKey(entry),
    ],
    queryFn: () => fetchSharePreview(strategyId, share, leverage, entry),
    refetchInterval: PREVIEW_REFRESH_MS,
  });
}
