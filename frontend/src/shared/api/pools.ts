import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";
import type { Pool } from "@/shared/api/types";

function isBalance(value: unknown): boolean {
  if (typeof value !== "object" || value === null) return false;
  const balance = value as Record<string, unknown>;
  return (
    typeof balance.total === "string" &&
    typeof balance.available === "string" &&
    typeof balance.observed_at === "string" &&
    typeof balance.stale === "boolean"
  );
}

function isPool(value: unknown): value is Pool {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.exchange === "string" &&
    row.exchange !== "" &&
    typeof row.venue === "string" &&
    typeof row.settlement_currency === "string" &&
    typeof row.enabled === "boolean" &&
    (row.balance === null || isBalance(row.balance)) &&
    typeof row.reserved === "string" &&
    (row.allocatable === null || typeof row.allocatable === "string")
  );
}

/**
 * `GET /api/pools`: a bare list, one object per pool and never a total (rule
 * 7). The body is validated row by row, because the exchange scope is built
 * from it: a payload that is not a list of pools must read as an error, never
 * as "no exchanges", or a malformed answer would hide every tab silently.
 */
export async function fetchPools(): Promise<Pool[]> {
  const body = await apiFetch<unknown>("/pools");
  if (!Array.isArray(body) || !body.every(isPool)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /pools: expected a list of pools",
    });
  }
  return body;
}

const POOLS_REFRESH_MS = 60_000;

/** Query key `['pools']`, refetched every 60 s to match `balance.sync` (design.md § 15). */
export function usePools() {
  return useQuery({
    queryKey: ["pools"],
    queryFn: fetchPools,
    refetchInterval: POOLS_REFRESH_MS,
  });
}
