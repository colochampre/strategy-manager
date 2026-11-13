import { useMutation, useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";
import { type Entry, entryKey, entryParams, entryReadOptions, NO_ENTRY, useEntry } from "@/shared/api/entry";
import { isStrategyUptime } from "@/shared/api/subscriptions";
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
    (value.description === null || typeof value.description === "string") &&
    (value.capital === null || typeof value.capital === "string") &&
    isCount(value.subscribers) &&
    typeof value.max_drawdown === "string" &&
    // Null with no closed trade: an answer, so a missing one is refused.
    (value.win_rate === null || typeof value.win_rate === "string") &&
    typeof value.enabled === "boolean" &&
    isStrategyUptime(value.uptime) &&
    // The cap on the leverage a reader may choose, a decimal string. Never absent: a missing one would read as no cap.
    typeof value.stop_loss_pct === "string"
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

/**
 * `GET /api/public/strategies/{id}`. A strategy off the list answers 404, to its own author too, except a strategy
 * turned private to a reader who holds a live seat on it (tasks.md J.1), and one opened by its link or a live code
 * (decision 41). A dead code answers 410 with why, and too many wrong codes 429.
 */
export async function fetchPublicStrategy(strategyId: string, entry: Entry = NO_ENTRY): Promise<PublicStrategy> {
  const params = entryParams(entry);
  const query = params.length === 0 ? "" : `?${params.join("&")}`;
  const body = await apiFetch<unknown>(`/public/strategies/${encodeURIComponent(strategyId)}${query}`);
  if (!isPublicStrategy(body)) {
    throw new ApiError(200, { detail: "Unexpected response shape from GET /public/strategies/{id}: expected a strategy" });
  }
  return body;
}

/** The whole list, under the key every subscribe and leave invalidates: the live count and the capital move with them. */
export function usePublicStrategies() {
  return useQuery({ queryKey: ["public-strategies"], queryFn: fetchPublicStrategies });
}

/** Read with the entry the page provides, under a key of its own, so another code reads again. */
export function usePublicStrategy(strategyId: string) {
  const entry = useEntry();
  return useQuery({
    queryKey: ["public-strategies", strategyId, ...entryKey(entry)],
    queryFn: () => fetchPublicStrategy(strategyId, entry),
    ...entryReadOptions(entry),
  });
}

/**
 * `POST /api/public/invite-codes/lookup`: the strategy a code opens, for a reader who knows only the code. The code
 * goes in the body. It is not spent; a wrong one is a 404, a dead one 410, too many wrong ones 429.
 */
export async function lookUpInviteCode(code: string): Promise<string> {
  const body = await apiFetch<unknown>("/public/invite-codes/lookup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  if (!isRecord(body) || typeof body.strategy_id !== "string" || body.strategy_id === "") {
    throw new ApiError(200, { detail: "Unexpected response shape from POST /public/invite-codes/lookup: expected a strategy id" });
  }
  return body.strategy_id;
}

export function useLookUpInviteCode() {
  return useMutation<string, Error, string>({ mutationFn: lookUpInviteCode });
}
