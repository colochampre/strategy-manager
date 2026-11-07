import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";
import { type Entry, entryKey, entryParams, NO_ENTRY, useEntry } from "@/shared/api/entry";
import type { PublicRecord } from "@/shared/api/types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCount(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 0;
}

function isCurvePoint(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.date === "string" &&
    typeof value.daily_return === "string" &&
    typeof value.index === "string" &&
    typeof value.drawdown === "string"
  );
}

function isMonth(value: unknown): boolean {
  return (
    isRecord(value) &&
    Number.isInteger(value.year) &&
    Number.isInteger(value.month) &&
    typeof value.return === "string"
  );
}

function isRange(value: unknown): boolean {
  return isRecord(value) && typeof value.range === "string" && typeof value.return === "string" && isCount(value.trade_count);
}

function isPair(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.pair === "string" &&
    isCount(value.trades) &&
    isCount(value.wins) &&
    value.wins <= value.trades &&
    typeof value.win_rate === "string" &&
    typeof value.return === "string"
  );
}

/**
 * A `PublicRecordBody`, field by field. Every ratio is a decimal string. A body that carries an amount (a pnl, a
 * currency) is not this record and is refused: the public record has no money, so one that has some is wrong.
 */
function isPublicRecord(value: unknown): value is PublicRecord {
  if (!isRecord(value)) return false;
  const money = ["total_pnl", "currency", "pool"].some((name) => name in value);
  return (
    !money &&
    typeof value.day_boundary === "string" &&
    (value.origin === null || typeof value.origin === "string") &&
    isCount(value.closed_trade_count) &&
    typeof value.max_drawdown === "string" &&
    Array.isArray(value.ranges) &&
    value.ranges.every(isRange) &&
    Array.isArray(value.curve) &&
    value.curve.every(isCurvePoint) &&
    Array.isArray(value.monthly) &&
    value.monthly.every(isMonth) &&
    Array.isArray(value.by_pair) &&
    value.by_pair.every(isPair)
  );
}

/**
 * `GET /api/public/strategies/{id}/record`. A 404 (a strategy off the public list) resolves to `null`: there is no
 * record to draw, which is an answer and not a fault. Any other failure, or a body that is not a record, throws.
 */
export async function fetchPublicRecord(strategyId: string, entry: Entry = NO_ENTRY): Promise<PublicRecord | null> {
  const params = entryParams(entry);
  const query = params.length === 0 ? "" : `?${params.join("&")}`;
  let body: unknown;
  try {
    body = await apiFetch<unknown>(`/public/strategies/${encodeURIComponent(strategyId)}/record${query}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
  if (!isPublicRecord(body)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /public/strategies/{id}/record: expected a record",
    });
  }
  return body;
}

/** Under `['public-strategies', id, 'record']`, so every subscribe and leave that refreshes the list refreshes it too. */
export function usePublicRecord(strategyId: string) {
  const entry = useEntry();
  return useQuery({
    queryKey: ["public-strategies", strategyId, "record", ...entryKey(entry)],
    queryFn: () => fetchPublicRecord(strategyId, entry),
  });
}
