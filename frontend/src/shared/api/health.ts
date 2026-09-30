import { useQuery } from "@tanstack/react-query";

import { API_BASE_URL } from "@/shared/api/config";

export interface Health {
  dryRun: boolean;
}

/**
 * `GET /health` is mounted on the app itself, outside `/api`, and needs no
 * token (`main.py`: `{"status": "ok", "dry_run": settings.dry_run}`), so it is
 * read with a plain `fetch` rather than `apiFetch`. Anything that is not a
 * 2xx with a boolean `dry_run` is an error: a malformed answer must never be
 * readable as "dry run is off".
 */
export async function fetchHealth(): Promise<Health> {
  const response = await fetch(`${API_BASE_URL}/health`);
  if (!response.ok) {
    throw new Error(`GET /health failed with status ${response.status}`);
  }
  const body: unknown = await response.json();
  const dryRun = (body as { dry_run?: unknown } | null)?.dry_run;
  if (typeof dryRun !== "boolean") {
    throw new Error("Unexpected response shape from GET /health: dry_run is not a boolean");
  }
  return { dryRun };
}

const HEALTH_REFRESH_MS = 60_000;

/** Query key `['health']`, fresh for 60 s (design.md § 15). */
export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    staleTime: HEALTH_REFRESH_MS,
    refetchInterval: HEALTH_REFRESH_MS,
  });
}
