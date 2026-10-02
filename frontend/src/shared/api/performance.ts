import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";
import type { PoolPerformance, StrategyPerformance } from "@/shared/api/types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The shape the panel reads, checked one level deep. A body that is not a
 * report must read as an error: treating it as an empty ledger would show
 * "No closed trades yet" for a pool whose data simply failed to arrive.
 */
function isPoolPerformance(value: unknown): value is PoolPerformance {
  if (!isRecord(value)) return false;
  return (
    typeof value.currency === "string" &&
    typeof value.total_pnl === "string" &&
    typeof value.max_drawdown === "string" &&
    isRecord(value.excluded) &&
    Array.isArray(value.ranges) &&
    Array.isArray(value.curve) &&
    Array.isArray(value.monthly)
  );
}

/**
 * `GET /api/performance/pools/{exchange}/{venue}/{ccy}`. A 404 ("no such pool")
 * resolves to `null`: the pool list named this pool a moment ago, so it is a
 * pool without a report, not a failure. Every other non-2xx status throws.
 */
export async function fetchPoolPerformance(
  exchange: string,
  venue: string,
  currency: string,
): Promise<PoolPerformance | null> {
  const path = [exchange, venue, currency].map(encodeURIComponent).join("/");
  let body: unknown;
  try {
    body = await apiFetch<unknown>(`/performance/pools/${path}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
  if (!isPoolPerformance(body)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /performance/pools: expected a pool report",
    });
  }
  return body;
}

/**
 * `GET /api/performance/strategies/{id}`. As for a pool, a 404 is a strategy
 * without a report (null) and any other failure, or a body that is not a
 * strategy report, throws.
 */
export async function fetchStrategyPerformance(strategyId: string): Promise<StrategyPerformance | null> {
  let body: unknown;
  try {
    body = await apiFetch<unknown>(`/performance/strategies/${encodeURIComponent(strategyId)}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
  if (!isPoolPerformance(body) || typeof (body as { strategy_id?: unknown }).strategy_id !== "string") {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /performance/strategies: expected a strategy report",
    });
  }
  return body as StrategyPerformance;
}

/** Query key `['performance','strategy',id]` (design.md § 15). */
export function useStrategyPerformance(strategyId: string) {
  return useQuery({
    queryKey: ["performance", "strategy", strategyId],
    queryFn: () => fetchStrategyPerformance(strategyId),
    staleTime: PERFORMANCE_STALE_MS,
  });
}

export function poolPerformanceKey(exchange: string, venue: string, currency: string) {
  return ["performance", "pool", exchange, venue, currency] as const;
}

const PERFORMANCE_STALE_MS = 60_000;

/** Query key `['performance','pool',ex,venue,ccy]`; every range arrives in the one body. */
export function usePoolPerformance(exchange: string, venue: string, currency: string) {
  return useQuery({
    queryKey: poolPerformanceKey(exchange, venue, currency),
    queryFn: () => fetchPoolPerformance(exchange, venue, currency),
    staleTime: PERFORMANCE_STALE_MS,
  });
}
