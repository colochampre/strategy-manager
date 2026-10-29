import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";
import type { Strategy, Subscription, SubscriptionStatus } from "@/shared/api/types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const STATUSES: readonly SubscriptionStatus[] = ["ACTIVE", "LEAVING", "ENDED"];

function isInstant(value: unknown): boolean {
  return value === null || typeof value === "string";
}

/** A `SubscriptionView`, field by field: the share is a decimal string, never a number. */
export function isSubscription(value: unknown): value is Subscription {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.strategy_id === "string" &&
    typeof value.pool_id === "number" &&
    typeof value.allocation_percent === "string" &&
    STATUSES.includes(value.status as SubscriptionStatus) &&
    isInstant(value.created_at) &&
    isInstant(value.left_at) &&
    isInstant(value.ended_at)
  );
}

/**
 * `PATCH /api/subscriptions/{id}` with only `allocation_percent`, sent as the string it is. The answer is
 * checked, as for a read, so the page never caches a body it cannot describe.
 */
export async function setSubscriptionShare(subscriptionId: string, value: string): Promise<Subscription> {
  const body = await apiFetch<unknown>(`/subscriptions/${encodeURIComponent(subscriptionId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ allocation_percent: value }),
  });
  if (!isSubscription(body)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from PATCH /subscriptions/{id}: expected a subscription",
    });
  }
  return body;
}

/**
 * Saves the signed-in user's share of a strategy. On success the checked answer is written into that
 * strategy's `subscription` under `['strategy', id]`, so the stored value the page shows is the confirmed
 * one even if the refetch that follows fails. Settled, not only success: a refusal says the stored state is
 * not what the page showed, so the list and the page (and the preview under its key) read it again. The
 * invalidation's promise is returned, so the mutation stays pending until the page holds the new state.
 */
export function useSetSubscriptionShare(strategyId: string, subscriptionId: string) {
  const queryClient = useQueryClient();
  return useMutation<Subscription, Error, string>({
    mutationFn: (value) => setSubscriptionShare(subscriptionId, value),
    onSuccess: (saved) => {
      queryClient.setQueryData<Strategy>(["strategy", strategyId], (held) =>
        held === undefined ? held : { ...held, subscription: saved },
      );
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["strategies"] });
      await queryClient.invalidateQueries({ queryKey: ["strategy", strategyId] });
    },
  });
}
