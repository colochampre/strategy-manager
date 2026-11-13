import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch, retryTransient } from "@/shared/api/client";
import { isStrategyUptime, isSubscription } from "@/shared/api/subscriptions";
import type {
  EnablementEvent,
  InviteCode,
  IssuedInviteCode,
  RegisteredStrategy,
  RegisterStrategyBody,
  Strategy,
  Visibility,
} from "@/shared/api/types";

const SECRET_LAST4_LENGTH = 4;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCount(value: unknown): boolean {
  return Number.isInteger(value) && (value as number) >= 0;
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
    // The share is the signed-in user's, on their subscription; null when they hold none. Never absent.
    (value.subscription === null || isSubscription(value.subscription)) &&
    typeof value.enabled === "boolean" &&
    (value.archived_at === null || typeof value.archived_at === "string") &&
    Array.isArray(value.allowed_pairs) &&
    isStrategyUptime(value.uptime) &&
    // When the strategy was made; null for a row older than the column. Never absent.
    (value.created_at === null || typeof value.created_at === "string") &&
    (value.visibility === "PUBLIC" || value.visibility === "LINK" || value.visibility === "PRIVATE") &&
    // Sent to the author while the strategy is LINK; null otherwise. Never absent.
    (value.share_token === null || typeof value.share_token === "string") &&
    // Exactly four characters: anything else is not the tail of a secret, and is not drawn as one.
    typeof value.secret_last4 === "string" &&
    value.secret_last4.length === SECRET_LAST4_LENGTH &&
    isCount(value.subscribers) &&
    isCount(value.live_subscribers) &&
    // The author's free text, or null when there is none. Never absent.
    (value.description === null || typeof value.description === "string") &&
    // Null under the brake, when nobody trades live. Never absent.
    (value.capital === null || typeof value.capital === "string") &&
    // The stop level, a decimal string. Never absent: a missing one would read as no cap.
    typeof value.stop_loss_pct === "string"
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

/** A secret the server issues: a non-empty string, or nothing. The body is never echoed into an error. */
function issuedSecret(body: unknown): string | null {
  const secret = isRecord(body) ? body.webhook_secret : undefined;
  return typeof secret === "string" && secret !== "" ? secret : null;
}

/**
 * `POST /api/strategies`. A new strategy is always disabled; arming it is a separate call. The answer carries the
 * webhook secret once, and only that is kept from it: the strategy itself is read again from the list.
 */
export async function registerStrategy(body: RegisterStrategyBody): Promise<RegisteredStrategy> {
  const answer = await apiFetch<unknown>("/strategies", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return { webhook_secret: issuedSecret(answer) };
}

/**
 * `POST /api/strategies/{id}/webhook-secret`: replaces the strategy's secret and answers the new one, once. The
 * old secret stops working at once. A body without a secret reads as an error with a fixed message.
 */
export async function regenerateWebhookSecret(strategyId: string): Promise<string> {
  const answer = await apiFetch<unknown>(`/strategies/${encodeURIComponent(strategyId)}/webhook-secret`, { method: "POST" });
  const secret = issuedSecret(answer);
  if (secret === null) {
    throw new ApiError(200, { detail: "Unexpected response shape from POST /strategies/{id}/webhook-secret: expected a secret" });
  }
  return secret;
}

/** `PATCH /api/strategies/{id}` with only `enabled`: every other field stays unchanged. */
export function setStrategyEnabled(strategyId: string, enabled: boolean): Promise<Strategy> {
  return apiFetch<Strategy>(`/strategies/${encodeURIComponent(strategyId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
}

/**
 * `PATCH /api/strategies/{id}` with only `name`: every other field stays unchanged. The caller trims it; the API
 * does not. The answer is checked, as for a read, so the page never caches a body it cannot describe.
 */
export async function setStrategyName(strategyId: string, name: string): Promise<Strategy> {
  const body = await apiFetch<unknown>(`/strategies/${encodeURIComponent(strategyId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!isStrategy(body)) {
    throw new ApiError(200, { detail: "Unexpected response shape from PATCH /strategies/{id}: expected a strategy" });
  }
  return body;
}

/** `PATCH /api/strategies/{id}` with only `visibility`. The answer is checked, as for a read. */
export async function setStrategyVisibility(strategyId: string, visibility: Visibility): Promise<Strategy> {
  const body = await apiFetch<unknown>(`/strategies/${encodeURIComponent(strategyId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ visibility }),
  });
  if (!isStrategy(body)) {
    throw new ApiError(200, { detail: "Unexpected response shape from PATCH /strategies/{id}: expected a strategy" });
  }
  return body;
}

/**
 * `PATCH /api/strategies/{id}` with only `description`: every other field stays unchanged. The text goes as typed
 * (the server trims it and reads a blank one as none); `null` clears it. The answer is checked, as for a read.
 */
export async function setStrategyDescription(strategyId: string, description: string | null): Promise<Strategy> {
  const body = await apiFetch<unknown>(`/strategies/${encodeURIComponent(strategyId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ description }),
  });
  if (!isStrategy(body)) {
    throw new ApiError(200, { detail: "Unexpected response shape from PATCH /strategies/{id}: expected a strategy" });
  }
  return body;
}

/**
 * `PATCH /api/strategies/{id}` with only `stop_loss_pct`: every other field stays unchanged. A change applies to
 * openings made after it; a position already open keeps the stop it has. The answer is checked, as for a read.
 */
export async function setStrategyStopLevel(strategyId: string, stopLossPct: string): Promise<Strategy> {
  const body = await apiFetch<unknown>(`/strategies/${encodeURIComponent(strategyId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stop_loss_pct: stopLossPct }),
  });
  if (!isStrategy(body)) {
    throw new ApiError(200, { detail: "Unexpected response shape from PATCH /strategies/{id}: expected a strategy" });
  }
  return body;
}

/** A row of the author's list of codes: an id, the last four characters and the expiry. Never the code. */
function isInviteCode(value: unknown): value is InviteCode {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.hint === "string" &&
    typeof value.expires_at === "string"
  );
}

function invitePath(strategyId: string): string {
  return `/strategies/${encodeURIComponent(strategyId)}/invite-codes`;
}

/** `GET /api/strategies/{id}/invite-codes`: the strategy's live codes, oldest first. Checked row by row. */
export async function fetchInviteCodes(strategyId: string): Promise<InviteCode[]> {
  const body = await apiFetch<unknown>(invitePath(strategyId));
  if (!Array.isArray(body) || !body.every(isInviteCode)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /strategies/{id}/invite-codes: expected a list of codes",
    });
  }
  return body;
}

/**
 * `POST /api/strategies/{id}/invite-codes`: a new code, answered once. A body without the code reads as an error
 * with a fixed message, which never echoes the body.
 */
export async function issueInviteCode(strategyId: string): Promise<IssuedInviteCode> {
  const body = await apiFetch<unknown>(invitePath(strategyId), { method: "POST" });
  const code = isRecord(body) ? body.code : undefined;
  if (!isInviteCode(body) || typeof code !== "string" || code === "") {
    throw new ApiError(200, { detail: "Unexpected response shape from POST /strategies/{id}/invite-codes: expected a code" });
  }
  return { id: body.id, hint: body.hint, expires_at: body.expires_at, code };
}

/** `DELETE /api/strategies/{id}/invite-codes/{code_id}`: the code stops opening the strategy at once. */
export async function revokeInviteCode(strategyId: string, codeId: string): Promise<void> {
  await apiFetch<void>(`${invitePath(strategyId)}/${encodeURIComponent(codeId)}`, { method: "DELETE" });
}

const inviteCodesKey = (strategyId: string) => ["strategy", strategyId, "invite-codes"] as const;

/**
 * The live codes of a PRIVATE strategy, read only while `enabled`. Under `['strategy', id]`, so a change of
 * visibility reads them again.
 */
export function useInviteCodes(strategyId: string, enabled: boolean) {
  return useQuery({
    queryKey: inviteCodesKey(strategyId),
    queryFn: () => fetchInviteCodes(strategyId),
    enabled,
  });
}

/**
 * Makes a code; the code is the mutation's `data`, shown once. `gcTime: 0`, as for the webhook secret: it leaves
 * the mutation cache as soon as nothing shows it. The list is read again whatever the outcome.
 */
export function useIssueInviteCode(strategyId: string) {
  const queryClient = useQueryClient();
  return useMutation<IssuedInviteCode, Error, void>({
    mutationFn: () => issueInviteCode(strategyId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: inviteCodesKey(strategyId) }),
    gcTime: 0,
  });
}

/** Revokes one code; the list is read again whatever the outcome, so a code already gone leaves it too. */
export function useRevokeInviteCode(strategyId: string) {
  const queryClient = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (codeId) => revokeInviteCode(strategyId, codeId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: inviteCodesKey(strategyId) }),
  });
}

/** Every strategy mutation ends here, so the list and the detail never show a stale state. */
export function useInvalidateStrategies() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["strategies"] });
}

/**
 * `gcTime: 0`: the mutation's result holds the secret that is shown once, and it leaves the mutation cache as
 * soon as nothing observes it (the dialog closing) instead of five minutes later.
 */
export function useRegisterStrategy() {
  const invalidate = useInvalidateStrategies();
  return useMutation<RegisteredStrategy, Error, RegisterStrategyBody>({
    mutationFn: registerStrategy,
    onSuccess: () => invalidate(),
    gcTime: 0,
  });
}

/**
 * Regenerates the secret; the new one is the mutation's `data`, evicted like the one `useRegisterStrategy` holds.
 * The strategy is read again on success, because its `secret_last4` changed with the secret.
 */
export function useRegenerateWebhookSecret(strategyId: string) {
  const queryClient = useQueryClient();
  return useMutation<string, Error, void>({
    mutationFn: () => regenerateWebhookSecret(strategyId),
    // Not awaited: the secret is shown once, and a slow read must not hold it back.
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["strategies"] });
      void queryClient.invalidateQueries({ queryKey: ["strategy", strategyId] });
    },
    gcTime: 0,
  });
}

/**
 * Changes who may subscribe. On success the checked answer is written into `['strategy', id]`, as a rename does;
 * settled, both keys are read again, so a refusal leaves the page on the stored state.
 */
export function useSetStrategyVisibility(strategyId: string) {
  const queryClient = useQueryClient();
  return useMutation<Strategy, Error, Visibility>({
    mutationFn: (visibility) => setStrategyVisibility(strategyId, visibility),
    onSuccess: (saved) => {
      queryClient.setQueryData(["strategy", strategyId], saved);
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["strategies"] });
      await queryClient.invalidateQueries({ queryKey: ["strategy", strategyId] });
    },
  });
}

/**
 * Changes the description. On success the checked answer is written into `['strategy', id]`, so the page shows
 * what the server kept (trimmed); settled, both keys are read again, so a refusal leaves the page on the stored state.
 */
export function useSetStrategyDescription(strategyId: string) {
  const queryClient = useQueryClient();
  return useMutation<Strategy, Error, string | null>({
    mutationFn: (description) => setStrategyDescription(strategyId, description),
    onSuccess: (saved) => {
      queryClient.setQueryData(["strategy", strategyId], saved);
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["strategies"] });
      await queryClient.invalidateQueries({ queryKey: ["strategy", strategyId] });
    },
  });
}

/** Changes the stop level, with the same effects on the cache as the description. */
export function useSetStrategyStopLevel(strategyId: string) {
  const queryClient = useQueryClient();
  return useMutation<Strategy, Error, string>({
    mutationFn: (stopLossPct) => setStrategyStopLevel(strategyId, stopLossPct),
    onSuccess: (saved) => {
      queryClient.setQueryData(["strategy", strategyId], saved);
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["strategies"] });
      await queryClient.invalidateQueries({ queryKey: ["strategy", strategyId] });
    },
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

/**
 * Renames the strategy. On success the checked answer is written into `['strategy', id]`, so the page shows
 * the confirmed name even if the refetch that follows fails; settled, both keys are read again.
 */
export function useRenameStrategy(strategyId: string) {
  const queryClient = useQueryClient();
  return useMutation<Strategy, Error, string>({
    mutationFn: (name) => setStrategyName(strategyId, name),
    onSuccess: (saved) => {
      queryClient.setQueryData(["strategy", strategyId], saved);
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["strategies"] });
      await queryClient.invalidateQueries({ queryKey: ["strategy", strategyId] });
    },
  });
}

function isEnablementEvent(value: unknown): value is EnablementEvent {
  return (
    isRecord(value) &&
    typeof value.enabled === "boolean" &&
    typeof value.occurred_at === "string" &&
    typeof value.origin === "string"
  );
}

/**
 * `GET /api/strategies/{id}`, archived ones included. The body is checked: a
 * payload that is not a strategy must read as an error, because the page would
 * otherwise render controls over a strategy it cannot describe.
 */
export async function fetchStrategy(strategyId: string): Promise<Strategy> {
  const body = await apiFetch<unknown>(`/strategies/${encodeURIComponent(strategyId)}`);
  if (!isStrategy(body)) {
    throw new ApiError(200, { detail: "Unexpected response shape from GET /strategies/{id}: expected a strategy" });
  }
  return body;
}

/** Query key `['strategy',id]`, invalidated by every mutation of that strategy (design.md § 15). */
export function useStrategy(strategyId: string) {
  return useQuery({
    queryKey: ["strategy", strategyId],
    queryFn: () => fetchStrategy(strategyId),
    retry: retryTransient,
  });
}

/** `GET /api/strategies/{id}/events`: every enable and disable, oldest first as the server writes them. */
export async function fetchStrategyEvents(strategyId: string): Promise<EnablementEvent[]> {
  const body = await apiFetch<unknown>(`/strategies/${encodeURIComponent(strategyId)}/events`);
  if (!Array.isArray(body) || !body.every(isEnablementEvent)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /strategies/{id}/events: expected a list of enablement events",
    });
  }
  return body;
}

/** Query key `['strategy',id,'events']`, under the strategy's own key so one invalidation refreshes both. */
export function useStrategyEvents(strategyId: string) {
  return useQuery({
    queryKey: ["strategy", strategyId, "events"],
    queryFn: () => fetchStrategyEvents(strategyId),
    retry: retryTransient,
  });
}

/** `POST /api/strategies/{id}/archive`. Refusals (409 `STILL_ENABLED`, `OPEN_POSITION`) are thrown with their reasons. */
export function archiveStrategy(strategyId: string): Promise<Strategy> {
  return apiFetch<Strategy>(`/strategies/${encodeURIComponent(strategyId)}/archive`, { method: "POST" });
}

/** `PUT /api/strategies/{id}/allowed-pairs`: the FULL set the strategy should end with, never a delta. */
export function replaceAllowedPairs(strategyId: string, pairs: readonly string[]): Promise<Strategy> {
  return apiFetch<Strategy>(`/strategies/${encodeURIComponent(strategyId)}/allowed-pairs`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pairs }),
  });
}

/**
 * Settled, not only success, for the same reason as the enable switch: a
 * refused change (409) says the stored state is not what the page showed, so
 * the page and the list read it again.
 */
function useInvalidateOnSettled(strategyId: string) {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ["strategies"] });
    await queryClient.invalidateQueries({ queryKey: ["strategy", strategyId] });
  };
}

export function useArchiveStrategy(strategyId: string) {
  const invalidate = useInvalidateOnSettled(strategyId);
  return useMutation<Strategy, Error, void>({
    mutationFn: () => archiveStrategy(strategyId),
    onSettled: invalidate,
  });
}

export function useReplaceAllowedPairs(strategyId: string) {
  const invalidate = useInvalidateOnSettled(strategyId);
  return useMutation<Strategy, Error, readonly string[]>({
    mutationFn: (pairs) => replaceAllowedPairs(strategyId, pairs),
    onSettled: invalidate,
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
