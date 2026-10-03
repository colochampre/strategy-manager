import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";
import type { RegisterStrategyBody, Strategy } from "@/shared/api/types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isUptime(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.seconds === "number" &&
    (value.first_enabled_at === null || typeof value.first_enabled_at === "string") &&
    typeof value.baseline === "boolean"
  );
}

function isStrategy(value: unknown): value is Strategy {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    typeof value.exchange === "string" &&
    typeof value.venue === "string" &&
    typeof value.settlement_currency === "string" &&
    (value.fill_mode === "SKIP" || value.fill_mode === "PARTIAL") &&
    typeof value.allocation_percent === "string" &&
    typeof value.enabled === "boolean" &&
    (value.archived_at === null || typeof value.archived_at === "string") &&
    Array.isArray(value.allowed_pairs) &&
    isUptime(value.uptime)
  );
}

/**
 * `GET /api/strategies`, archived ones only when asked (`include_archived`).
 * The body is checked row by row: a payload that is not a list of strategies
 * must read as an error, because an empty list would tell the operator there
 * is nothing to manage.
 */
export async function fetchStrategies(includeArchived: boolean): Promise<Strategy[]> {
  const query = includeArchived ? "?include_archived=true" : "";
  const body = await apiFetch<unknown>(`/strategies${query}`);
  if (!Array.isArray(body) || !body.every(isStrategy)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /strategies: expected a list of strategies",
    });
  }
  return body;
}

/** Query key `['strategies',{includeArchived}]`, invalidated by every strategy mutation (design.md § 15). */
export function useStrategies(includeArchived: boolean) {
  return useQuery({
    queryKey: ["strategies", { includeArchived }],
    queryFn: () => fetchStrategies(includeArchived),
  });
}

/** `POST /api/strategies`. A new strategy is always disabled; arming it is a separate call. */
export function registerStrategy(body: RegisterStrategyBody): Promise<Strategy> {
  return apiFetch<Strategy>("/strategies", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** `PATCH /api/strategies/{id}` with only `enabled`: every other field stays unchanged. */
export function setStrategyEnabled(strategyId: string, enabled: boolean): Promise<Strategy> {
  return apiFetch<Strategy>(`/strategies/${encodeURIComponent(strategyId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
}

/** Every strategy mutation ends here, so the list and the detail never show a stale state. */
export function useInvalidateStrategies() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["strategies"] });
}

export function useRegisterStrategy() {
  const invalidate = useInvalidateStrategies();
  return useMutation<Strategy, Error, RegisterStrategyBody>({
    mutationFn: registerStrategy,
    onSuccess: () => invalidate(),
  });
}

export function useSetStrategyEnabled(strategyId: string) {
  const queryClient = useQueryClient();
  return useMutation<Strategy, Error, boolean>({
    mutationFn: (enabled) => setStrategyEnabled(strategyId, enabled),
    // Settled, not only success: a refused change (409) says the stored state is not what the row showed.
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["strategies"] });
      await queryClient.invalidateQueries({ queryKey: ["strategy", strategyId] });
    },
  });
}

/** `DELETE /api/strategies/{id}`: 204 and no body. Refusals (404, 409) are thrown as `ApiError`. */
export function deleteStrategy(strategyId: string): Promise<void> {
  return apiFetch<void>(`/strategies/${encodeURIComponent(strategyId)}`, { method: "DELETE" });
}

/**
 * Deletes a strategy that has no history. A 404 is read as "already gone" (a
 * double click, or another tab, got there first), so it resolves and runs the
 * same cache effects as a 204. Any other refusal is thrown with its code and
 * its history counts (`ApiError.code`, `ApiError.fields`), and no cache moves.
 *
 * The strategy's own queries are REMOVED, not invalidated: an invalidation
 * would refetch a detail that now answers 404 and flash an error before the
 * caller navigates away. The prefix covers the events and performance queries.
 */
export function useDeleteStrategy(strategyId: string) {
  const queryClient = useQueryClient();
  return useMutation<void, Error, void>({
    mutationFn: async () => {
      try {
        await deleteStrategy(strategyId);
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 404)) throw error;
      }
    },
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: ["strategy", strategyId] });
      await queryClient.invalidateQueries({ queryKey: ["strategies"] });
    },
  });
}
