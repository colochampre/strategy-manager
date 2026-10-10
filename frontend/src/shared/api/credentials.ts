import { useQuery } from "@tanstack/react-query";

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

export async function fetchCredentials(): Promise<CredentialEntry[]> {
  return [];
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
