import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";

/**
 * One exchange of `GET /api/credentials`. A `STORED` row carries the last four
 * characters of the key and the facts recorded with it; an `EMPTY` row is the
 * exchange and its status, and everything else is null on the wire.
 */
export interface StoredCredential {
  exchange: string;
  status: "STORED";
  last4: string;
  trade_capable: boolean;
  trade_capability_source: string;
  trade_confirmed_at: string | null;
  withdraw_check: string;
  withdraw_confirmed_at: string | null;
  validated_at: string | null;
  stored_at: string | null;
  internal_transfer: boolean | null;
}

export interface EmptyCredential {
  exchange: string;
  status: "EMPTY";
}

export type CredentialEntry = StoredCredential | EmptyCredential;

/** Why a save ended without storing the key, or without the panel being able to say. */
export type SaveRefusal =
  | "keyRejected"
  | "withdrawPermission"
  | "permissionsUnavailable"
  | "venueUnreachable"
  | "concurrentSave"
  | "confirmationRequired"
  | "confirmationNotApplicable"
  | "notServed"
  | "storageUnavailable"
  | "invalidKey"
  | "invalidSecret"
  | "invalidRequest"
  | "noAnswer"
  | "unknown";

export type SaveResult =
  | { kind: "saved"; last4: string | null; readOnly: boolean }
  | { kind: "refused"; reason: SaveRefusal; missing: readonly string[]; status: number }
  | { kind: "unauthorized" };

const LAST4_LENGTH = 4;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringOrNull(value: unknown): boolean {
  return value === null || typeof value === "string";
}

/**
 * A row is believed only when every field the panel draws is of the type it
 * will be drawn as. `last4` is exactly four characters: a server fault that put
 * a whole key there would otherwise be drawn on every card and tab.
 */
function isCredentialEntry(value: unknown): value is CredentialEntry {
  if (!isRecord(value)) return false;
  if (typeof value.exchange !== "string" || value.exchange === "") return false;
  if (value.status === "EMPTY") return true;
  return (
    value.status === "STORED" &&
    typeof value.last4 === "string" &&
    value.last4.length === LAST4_LENGTH &&
    typeof value.trade_capable === "boolean" &&
    typeof value.trade_capability_source === "string" &&
    typeof value.withdraw_check === "string" &&
    isStringOrNull(value.validated_at) &&
    isStringOrNull(value.stored_at) &&
    isStringOrNull(value.trade_confirmed_at) &&
    isStringOrNull(value.withdraw_confirmed_at) &&
    (value.internal_transfer === null || typeof value.internal_transfer === "boolean")
  );
}

/**
 * `GET /api/credentials`: a bare list, one object per exchange the server
 * knows. The body is checked row by row, because the Settings page and the
 * exchange tabs are drawn from it: a body that is not a list of such rows must
 * read as an error with "Try again", never as "no keys", or a malformed answer
 * would say that a stored key does not exist.
 */
export async function fetchCredentials(): Promise<CredentialEntry[]> {
  const body = await apiFetch<unknown>("/credentials");
  if (!Array.isArray(body) || !body.every(isCredentialEntry)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /credentials: expected a list of exchange keys",
    });
  }
  return body;
}

/** Query key `['credentials']`. */
export function useCredentials() {
  return useQuery({
    queryKey: ["credentials"],
    queryFn: fetchCredentials,
  });
}

/** The seven outcomes the save route answers with, and the refusal each one is. */
const REFUSAL_BY_OUTCOME: ReadonlyMap<string, SaveRefusal> = new Map<string, SaveRefusal>([
  ["KEY_REJECTED", "keyRejected"],
  ["WITHDRAW_PERMISSION", "withdrawPermission"],
  ["PERMISSIONS_UNAVAILABLE", "permissionsUnavailable"],
  ["VENUE_UNREACHABLE", "venueUnreachable"],
  ["CONCURRENT_SAVE", "concurrentSave"],
  ["CONFIRMATION_REQUIRED", "confirmationRequired"],
  ["CONFIRMATION_NOT_APPLICABLE", "confirmationNotApplicable"],
]);

const READ_ONLY_WARNING = "READ_ONLY_KEY";

/** The status the save route answers on success; `apiFetch` does not hand over the one it read. */
const UNREADABLE_SUCCESS_STATUS = 200;

function refused(reason: SaveRefusal, status: number, missing: readonly string[] = []): SaveResult {
  return { kind: "refused", reason, missing, status };
}

/**
 * What the panel keeps of a save that worked: the last four characters, only
 * when the server's is exactly four, and whether the key cannot trade. Taken
 * from the answer itself, never cut from what was typed, and never from the
 * list that is read after it (that read can fail).
 */
function savedFrom(body: unknown): SaveResult {
  const record = isRecord(body) ? body : {};
  const facts = isRecord(record.facts) ? record.facts : {};
  const warnings = Array.isArray(record.warnings) ? record.warnings : [];
  const last4 = typeof record.last4 === "string" && record.last4.length === LAST4_LENGTH ? record.last4 : null;
  const readOnly = warnings.includes(READ_ONLY_WARNING) || facts.trade_capable === false;
  return { kind: "saved", last4, readOnly };
}

/** The names a CONFIRMATION_REQUIRED lists at the top level of its body; a non-list gives none. */
function missingFrom(error: ApiError): string[] {
  const missing = error.responseBody?.missing;
  return Array.isArray(missing) ? missing.filter((name): name is string => typeof name === "string") : [];
}

/** A pydantic 422 holds a list of `{type, loc, msg}`; the field a refusal is about is the end of `loc`. */
function validationReason(detail: readonly unknown[]): SaveRefusal {
  const fields = detail.map((entry) => (isRecord(entry) && Array.isArray(entry.loc) ? entry.loc.at(-1) : undefined));
  if (fields.includes("api_key")) return "invalidKey";
  if (fields.includes("api_secret")) return "invalidSecret";
  return "invalidRequest";
}

/** First match wins: a 401; a known outcome; a 404; a 503; a 422 whose `detail` is a list; status 0; anything else. */
function refusalFrom(error: ApiError): SaveResult {
  if (error.status === 401) return { kind: "unauthorized" };
  const byOutcome = typeof error.outcome === "string" ? REFUSAL_BY_OUTCOME.get(error.outcome) : undefined;
  if (byOutcome !== undefined) {
    return refused(byOutcome, error.status, byOutcome === "confirmationRequired" ? missingFrom(error) : []);
  }
  if (error.status === 404) return refused("notServed", error.status);
  if (error.status === 503) return refused("storageUnavailable", error.status);
  const detail = error.responseBody?.detail;
  if (error.status === 422 && Array.isArray(detail)) return refused(validationReason(detail), error.status);
  if (error.status === 0) return refused("noAnswer", 0);
  return refused("unknown", error.status);
}

/**
 * `PUT /api/credentials/{exchange}`. A plain function over `apiFetch`, never a
 * `useMutation`: a mutation keeps its `variables`, which would be the secret,
 * in the mutation cache. It catches everything, maps it, and lets the error
 * object go, so what it resolves is a plain object of known fields and never
 * holds the server's wording nor anything that was typed. It never retries: a
 * second request is a second signed read at the venue.
 *
 * The text of a refusal is chosen by the page from `reason`; the server's
 * `detail` is never carried out of here.
 */
export async function saveCredential(
  exchange: string,
  apiKey: string,
  apiSecret: string,
  confirmations: readonly string[],
): Promise<SaveResult> {
  const body: Record<string, unknown> = { api_key: apiKey, api_secret: apiSecret };
  for (const name of confirmations) {
    body[name] = true;
  }
  try {
    const answer = await apiFetch<unknown>(`/credentials/${encodeURIComponent(exchange)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return savedFrom(answer);
  } catch (error) {
    if (error instanceof ApiError) return refusalFrom(error);
    // The only unguarded await in `apiFetch` is the 2xx body, so a `SyntaxError`
    // is a success status with a body that is not JSON. This route always answers
    // JSON: such a body came from something else on the way, and the panel does
    // not know whether the key was stored. Saying "saved" here would be a guess
    // shown as a fact, with nothing anywhere to contradict it.
    if (error instanceof SyntaxError) return refused("unknown", UNREADABLE_SUCCESS_STATUS);
    return refused("noAnswer", 0);
  }
}

/** What stands in the way of a delete, as the server listed it; only the names of strategies are kept, the other ids are counted. */
export interface NotFlatLists {
  enabledStrategies: readonly string[];
  symbols: readonly string[];
  allocations: number;
  liveReservations: number;
  inFlightAttempts: number;
}

/** How a delete ended. `lists` is null for a refusal whose five lists cannot all be read. */
export type DeleteResult =
  | { kind: "deleted" }
  | { kind: "notFlat"; lists: NotFlatLists | null }
  | { kind: "gone" }
  | { kind: "unknown" }
  | { kind: "unauthorized" };

/** The outcome the delete route answers with when the exchange still has exposure. */
const NOT_FLAT = "EXCHANGE_NOT_FLAT";

function isTexts(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === "string");
}

/**
 * The five lists of a refusal, or null. Never half a list: when any of the five is missing or is not a list, or a
 * strategy has no name, none of them is trusted, because a line that left out one thing in the way would let the
 * owner believe the rest is all there is. Strategies are kept by name (shown as text); every other list is counted.
 */
function listsFrom(body: Readonly<Record<string, unknown>> | undefined): NotFlatLists | null {
  if (body === undefined) return null;
  const { enabled_strategies: strategies, symbols, allocations, live_reservations: reservations } = body;
  const attempts = body.in_flight_attempts;
  if (!Array.isArray(strategies)) return null;
  const names: string[] = [];
  for (const entry of strategies) {
    if (!isRecord(entry) || typeof entry.name !== "string" || entry.name === "") return null;
    names.push(entry.name);
  }
  if (!isTexts(symbols) || !isTexts(allocations) || !isTexts(reservations) || !isTexts(attempts)) return null;
  return {
    enabledStrategies: names,
    symbols,
    allocations: allocations.length,
    liveReservations: reservations.length,
    inFlightAttempts: attempts.length,
  };
}

/** A 401; a 404; a 409 that is the refusal the panel knows; anything else, which includes no answer. */
function deleteOutcomeFrom(error: ApiError): DeleteResult {
  if (error.status === 401) return { kind: "unauthorized" };
  if (error.status === 404) return { kind: "gone" };
  if (error.status === 409 && error.outcome === NOT_FLAT) {
    return { kind: "notFlat", lists: listsFrom(error.responseBody) };
  }
  return { kind: "unknown" };
}

/**
 * `DELETE /api/credentials/{exchange}`. Catches everything and resolves a plain object of known fields: the
 * server's `detail` never leaves here, and the text of every outcome is chosen by the dialog. It never retries.
 * A 404 is `gone`, never a success: the same status also means "not served". An answer that cannot be read is
 * `unknown`, because the key may have been deleted.
 */
export async function deleteCredential(exchange: string): Promise<DeleteResult> {
  try {
    await apiFetch<unknown>(`/credentials/${encodeURIComponent(exchange)}`, { method: "DELETE" });
    return { kind: "deleted" };
  } catch (error) {
    if (error instanceof ApiError) return deleteOutcomeFrom(error);
    // A 2xx whose body is not JSON (a `SyntaxError`) or any other failure: the panel does not know what answered.
    return { kind: "unknown" };
  }
}

/**
 * The delete as a mutation, as archiving a strategy is: it carries only the exchange id, so nothing sensitive can
 * sit in the mutation cache. On every settled attempt but a 401 it reads both lists again and waits for them
 * before it reports, so the card behind a dialog is already the new one when the dialog closes. The re-read is
 * given to the hook and not to `mutate`, so it also runs when the dialog or the page has left the document.
 */
export function useDeleteCredential() {
  const queryClient = useQueryClient();
  return useMutation<DeleteResult, Error, string>({
    mutationFn: deleteCredential,
    onSettled: async (result) => {
      if (result?.kind === "unauthorized") return;
      await Promise.all([
        queryClient.refetchQueries({ queryKey: ["credentials"] }),
        queryClient.refetchQueries({ queryKey: ["pools"] }),
      ]);
    },
  });
}
