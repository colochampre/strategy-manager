import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";
import { type Entry, entryBody, NO_ENTRY, useEntry } from "@/shared/api/entry";
import type { HeldSubscription, Strategy, Subscription, SubscriptionStatus } from "@/shared/api/types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const STATUSES: readonly SubscriptionStatus[] = ["ACTIVE", "LEAVING", "ENDED"];
const HELD_KEY = ["subscriptions", "held"];

function isInstant(value: unknown): boolean {
  return value === null || typeof value === "string";
}

/** An `UptimeView`: seconds enabled, the first enable (null when never) and whether that first date is a baseline. */
export function isStrategyUptime(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.seconds === "number" &&
    (value.first_enabled_at === null || typeof value.first_enabled_at === "string") &&
    typeof value.baseline === "boolean"
  );
}

/** A `SubscriptionView`, field by field: the share is a decimal string, never a number. */
export function isSubscription(value: unknown): value is Subscription {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.strategy_id === "string" &&
    typeof value.pool_id === "number" &&
    typeof value.allocation_percent === "string" &&
    typeof value.leverage === "number" &&
    Number.isInteger(value.leverage) &&
    STATUSES.includes(value.status as SubscriptionStatus) &&
    isInstant(value.created_at) &&
    isInstant(value.left_at) &&
    isInstant(value.ended_at)
  );
}

/** `PATCH /api/subscriptions/{id}` with the given fields. The answer is checked, as for a read, so the page never caches a body it cannot describe. */
async function patchSubscription(subscriptionId: string, fields: Record<string, string | number>): Promise<Subscription> {
  const body = await apiFetch<unknown>(`/subscriptions/${encodeURIComponent(subscriptionId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  if (!isSubscription(body)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from PATCH /subscriptions/{id}: expected a subscription",
    });
  }
  return body;
}

/** `PATCH /api/subscriptions/{id}` with only `allocation_percent`, sent as the string it is. */
export async function setSubscriptionShare(subscriptionId: string, value: string): Promise<Subscription> {
  return patchSubscription(subscriptionId, { allocation_percent: value });
}

/** `PATCH /api/subscriptions/{id}` with only `leverage`, sent as the JSON integer it is. */
export async function setSubscriptionLeverage(subscriptionId: string, leverage: number): Promise<Subscription> {
  return patchSubscription(subscriptionId, { leverage });
}

/**
 * What a saved subscription field does to the cache. On success the checked answer is written into that
 * strategy's `subscription` under `['strategy', id]`, so the stored value the page shows is the confirmed
 * one even if the refetch that follows fails. Settled, not only success: a refusal says the stored state is
 * not what the page showed, so the list and the page (and the preview under its key) read it again. The
 * invalidation's promise is returned, so the mutation stays pending until the page holds the new state.
 */
function useSubscriptionSavedEffects(strategyId: string) {
  const queryClient = useQueryClient();
  return {
    onSuccess: (saved: Subscription) => {
      queryClient.setQueryData<Strategy>(["strategy", strategyId], (held) =>
        held === undefined ? held : { ...held, subscription: saved },
      );
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["strategies"] });
      await queryClient.invalidateQueries({ queryKey: ["strategy", strategyId] });
      await queryClient.invalidateQueries({ queryKey: HELD_KEY });
      await queryClient.invalidateQueries({ queryKey: ["public-strategies"] });
    },
  };
}

/** Saves the signed-in user's share of a strategy (see `useSubscriptionSavedEffects` for what it does to the cache). */
export function useSetSubscriptionShare(strategyId: string, subscriptionId: string) {
  const effects = useSubscriptionSavedEffects(strategyId);
  return useMutation<Subscription, Error, string>({
    mutationFn: (value) => setSubscriptionShare(subscriptionId, value),
    ...effects,
  });
}

/** Saves the signed-in user's leverage on a strategy's subscription, with the same effects on the cache as the share. */
export function useSetSubscriptionLeverage(strategyId: string, subscriptionId: string) {
  const effects = useSubscriptionSavedEffects(strategyId);
  return useMutation<Subscription, Error, number>({
    mutationFn: (leverage) => setSubscriptionLeverage(subscriptionId, leverage),
    ...effects,
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
    typeof row.settlement_currency === "string" &&
    typeof row.strategy_enabled === "boolean" &&
    isStrategyUptime(row.strategy_uptime) &&
    // The cap on this seat's leverage, a decimal string. Never absent.
    typeof row.stop_loss_pct === "string"
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

/**
 * `POST /api/subscriptions`: the signed-in user takes a place in the strategy, through their own pool on its market.
 * A strategy off the list takes the link or the code the reader entered with; a code is spent with the seat.
 */
export async function subscribe(
  strategyId: string,
  share: string,
  leverage: number,
  entry: Entry = NO_ENTRY,
): Promise<Subscription> {
  const body = await apiFetch<unknown>("/subscriptions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ strategy_id: strategyId, allocation_percent: share, leverage, ...entryBody(entry) }),
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
  const entry = useEntry();
  return useMutation<Subscription, Error, { share: string; leverage: number }>({
    mutationFn: ({ share, leverage }) => subscribe(strategyId, share, leverage, entry),
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
