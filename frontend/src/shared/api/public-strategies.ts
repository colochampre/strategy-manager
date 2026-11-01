import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";
import type { PublicStrategy } from "@/shared/api/types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCount(value: unknown): boolean {
  return Number.isInteger(value) && (value as number) >= 0;
}

/**
 * A `PublicStrategyBody`, field by field. Money and the return are decimal strings, never numbers. A null capital
 * is the brake, so it is an answer; a missing one is not.
 */
function isPublicStrategy(value: unknown): value is PublicStrategy {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    typeof value.author_name === "string" &&
    typeof value.exchange === "string" &&
    typeof value.venue === "string" &&
    typeof value.settlement_currency === "string" &&
    typeof value.created_at === "string" &&
    isCount(value.closed_trade_count) &&
    typeof value.unleveraged_return_before_fees === "string" &&
    isCount(value.live_subscribers) &&
    (value.capital === null || typeof value.capital === "string")
  );
}

/** `GET /api/public/strategies`. A body that is not a list of strategies is an error: an empty list would say nobody published one. */
export async function fetchPublicStrategies(): Promise<PublicStrategy[]> {
  const body = await apiFetch<unknown>("/public/strategies");
  if (!Array.isArray(body) || !body.every(isPublicStrategy)) {
    throw new ApiError(200, { detail: "Unexpected response shape from GET /public/strategies: expected a list" });
  }
  return body;
}

/** `GET /api/public/strategies/{id}`. A strategy off the list answers 404, to its own author too. */
export async function fetchPublicStrategy(strategyId: string): Promise<PublicStrategy> {
  const body = await apiFetch<unknown>(`/public/strategies/${encodeURIComponent(strategyId)}`);
  if (!isPublicStrategy(body)) {
    throw new ApiError(200, { detail: "Unexpected response shape from GET /public/strategies/{id}: expected a strategy" });
  }
  return body;
}

/** The whole list, under the key every subscribe and leave invalidates: the live count and the capital move with them. */
export function usePublicStrategies() {
  return useQuery({ queryKey: ["public-strategies"], queryFn: fetchPublicStrategies });
}

export function usePublicStrategy(strategyId: string) {
  return useQuery({ queryKey: ["public-strategies", strategyId], queryFn: () => fetchPublicStrategy(strategyId) });
}
