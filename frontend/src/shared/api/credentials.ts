import { useQuery } from "@tanstack/react-query";

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

export async function saveCredential(
  _exchange: string,
  _apiKey: string,
  _apiSecret: string,
  _confirmations: readonly string[],
): Promise<SaveResult> {
  return { kind: "refused", reason: "unknown", missing: [], status: 0 };
}
