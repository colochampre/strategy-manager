import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";
import type { HeldSubscription, Strategy, Subscription, SubscriptionStatus } from "@/shared/api/types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const STATUSES: readonly SubscriptionStatus[] = ["ACTIVE", "LEAVING", "ENDED"];
const HELD_KEY = ["subscriptions", "held"];

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
      await queryClient.invalidateQueries({ queryKey: HELD_KEY });
    },
  });
}

/** A live subscription and the strings that name its strategy; the author's name is null until they choose one. */
function isHeldSubscription(value: unknown): value is HeldSubscription {
  if (!isSubscription(value)) return false;
  const row = value as unknown as Record<string, unknown>;
  return (
    typeof row.strategy_name === "string" &&
    (row.author_name === null || typeof row.author_name === "string") &&
    typeof row.authored === "boolean" &&
    typeof row.exchange === "string" &&
    typeof row.venue === "string" &&
    typeof row.settlement_currency === "string"
  );
}

/** `GET /api/subscriptions/held`. A body that is not a list of them is an error, never "you hold nothing". */
export async function fetchHeldSubscriptions(): Promise<HeldSubscription[]> {
  const body = await apiFetch<unknown>("/subscriptions/held");
  if (!Array.isArray(body) || !body.every(isHeldSubscription)) {
    throw new ApiError(200, { detail: "Unexpected response shape from GET /subscriptions/held: expected a list" });
  }
  return body;
}

/** Query key `['subscriptions','held']`, invalidated by every subscribe, leave and share change. */
export function useHeldSubscriptions() {
  return useQuery({ queryKey: HELD_KEY, queryFn: fetchHeldSubscriptions });
}

/** `POST /api/subscriptions`: the signed-in user takes a place in the strategy, through their own pool on its market. */
export async function subscribe(strategyId: string, share: string): Promise<Subscription> {
  const body = await apiFetch<unknown>("/subscriptions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ strategy_id: strategyId, allocation_percent: share }),
  });
  if (!isSubscription(body)) {
    throw new ApiError(200, { detail: "Unexpected response shape from POST /subscriptions: expected a subscription" });
  }
  return body;
}

/** `POST /api/subscriptions/{id}/leave`: ended at once, or LEAVING while a position of it is still open. */
export async function leaveSubscription(subscriptionId: string): Promise<Subscription> {
  const body = await apiFetch<unknown>(`/subscriptions/${encodeURIComponent(subscriptionId)}/leave`, { method: "POST" });
  if (!isSubscription(body)) {
    throw new ApiError(200, { detail: "Unexpected response shape from POST /subscriptions/{id}/leave: expected a subscription" });
  }
  return body;
}

/**
 * Every read that names who holds a strategy, and waits for them. On settled and not only on success: a refusal
 * says the page believed something the server does not, and the live count and the capital move with a seat.
 */
function useReadsOfWhoHolds(strategyId: string) {
  const queryClient = useQueryClient();
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: HELD_KEY }),
      queryClient.invalidateQueries({ queryKey: ["strategies"] }),
      queryClient.invalidateQueries({ queryKey: ["strategy", strategyId] }),
      queryClient.invalidateQueries({ queryKey: ["public-strategies"] }),
    ]);
  };
}

export function useSubscribe(strategyId: string) {
  const reread = useReadsOfWhoHolds(strategyId);
  return useMutation<Subscription, Error, string>({
    mutationFn: (share) => subscribe(strategyId, share),
    onSettled: reread,
  });
}

export function useLeaveSubscription(strategyId: string, subscriptionId: string) {
  const reread = useReadsOfWhoHolds(strategyId);
  return useMutation<Subscription, Error, void>({
    mutationFn: () => leaveSubscription(subscriptionId),
    onSettled: reread,
  });
}
