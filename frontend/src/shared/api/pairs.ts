import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";
import type { AvailablePairs, PoolKey } from "@/shared/api/types";

function isPoolKey(value: unknown): value is PoolKey {
  if (typeof value !== "object" || value === null) return false;
  const pool = value as Record<string, unknown>;
  return (
    typeof pool.exchange === "string" &&
    typeof pool.venue === "string" &&
    typeof pool.settlement_currency === "string"
  );
}

function isAvailablePairsFor(value: unknown, pool: PoolKey): value is AvailablePairs {
  if (typeof value !== "object" || value === null) return false;
  const body = value as Record<string, unknown>;
  return (
    isPoolKey(body.pool) &&
    body.pool.exchange === pool.exchange &&
    body.pool.venue === pool.venue &&
    body.pool.settlement_currency === pool.settlement_currency &&
    Array.isArray(body.pairs) &&
    body.pairs.every((pair) => typeof pair === "string") &&
    body.count === body.pairs.length
  );
}

/**
 * `GET /api/pools/{exchange}/{venue}/{ccy}/available-pairs`: the pairs a pool's
 * venue lists, sorted, in market-key form. The body is validated because the
 * selector offers exactly this list and nothing else: a malformed answer must
 * read as an error, never as "no pairs", and an answer that names another pool
 * or whose count disagrees with its list must not be offered either.
 */
export async function fetchAvailablePairs(pool: PoolKey): Promise<AvailablePairs> {
  const segments = [pool.exchange, pool.venue, pool.settlement_currency].map(encodeURIComponent);
  const body = await apiFetch<unknown>(`/pools/${segments.join("/")}/available-pairs`);
  if (!isAvailablePairsFor(body, pool)) {
    throw new ApiError(200, {
      detail:
        "Unexpected response shape from GET /pools/{exchange}/{venue}/{ccy}/available-pairs: " +
        "expected this pool's sorted list of pairs and its count",
    });
  }
  return body;
}

/** The server caches the list for five minutes; the client keeps it fresh for as long. */
const AVAILABLE_PAIRS_STALE_MS = 5 * 60 * 1000;

/**
 * Query key `['available-pairs', exchange, venue, ccy]`, deliberately not under
 * `['pools']`, which refetches every 60 s (design.md addendum § G). Nothing is
 * fetched until a pool is chosen.
 */
export function useAvailablePairs(pool: PoolKey | null) {
  return useQuery({
    queryKey: ["available-pairs", pool?.exchange, pool?.venue, pool?.settlement_currency],
    queryFn: () => {
      if (pool === null) throw new Error("useAvailablePairs ran with no pool chosen");
      return fetchAvailablePairs(pool);
    },
    enabled: pool !== null,
    staleTime: AVAILABLE_PAIRS_STALE_MS,
    retry: 1,
  });
}
