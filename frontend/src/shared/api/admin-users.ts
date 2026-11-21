import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";
import type { Mode } from "@/shared/api/me";

/** What the user gave at sign-up, as the privacy policy says the admin sees it (public-site LS3). */
export interface AdminIdentity {
  first_name: string;
  last_name: string;
  cuit: string;
  country: string;
}

/**
 * One user as the admin sees them (decision 8): their state, and no amount and no performance. An exchange in
 * `exchanges_with_no_key` has an enabled pool and no active key, which is what the database can say of a degraded
 * one.
 */
export interface AdminUser {
  id: string;
  email: string;
  /** When the administrator suspended the account, or `null` while it is not suspended. */
  suspended_at: string | null;
  display_name: string | null;
  mode: Mode;
  exchanges_with_key: string[];
  exchanges_with_no_key: string[];
  subscriptions: number;
  open_positions: number;
  last_seen_at: string;
  /** `null` until the user signs up. */
  identity: AdminIdentity | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCount(value: unknown): boolean {
  return Number.isInteger(value) && (value as number) >= 0;
}

function isTextList(value: unknown): boolean {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isIdentity(value: unknown): value is AdminIdentity {
  if (!isRecord(value)) return false;
  return (
    typeof value.first_name === "string" &&
    typeof value.last_name === "string" &&
    typeof value.cuit === "string" &&
    typeof value.country === "string"
  );
}

/** An `AdminUserBody`, field by field. A null name is a user who has not chosen one, so it is an answer; a missing one is not. */
function isAdminUser(value: unknown): value is AdminUser {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.email === "string" &&
    (value.suspended_at === null || typeof value.suspended_at === "string") &&
    (value.display_name === null || typeof value.display_name === "string") &&
    (value.mode === "LIVE" || value.mode === "SIMULATION") &&
    isTextList(value.exchanges_with_key) &&
    isTextList(value.exchanges_with_no_key) &&
    isCount(value.subscriptions) &&
    isCount(value.open_positions) &&
    typeof value.last_seen_at === "string" &&
    (value.identity === null || isIdentity(value.identity))
  );
}

/** `GET /api/admin/users`. A body that is not a list of users is an error: an empty list would say nobody signed in. */
export async function fetchAdminUsers(): Promise<AdminUser[]> {
  const body = await apiFetch<unknown>("/admin/users");
  if (!Array.isArray(body) || !body.every(isAdminUser)) {
    throw new ApiError(200, { detail: "Unexpected response shape from GET /admin/users: expected a list" });
  }
  return body;
}

export type SetSuspensionResult =
  | { kind: "changed" }
  | { kind: "yourself" }
  | { kind: "notFound" }
  | { kind: "accountChanged" }
  | { kind: "unknown" };

/** `PUT /api/admin/users/{id}/suspension`: suspends or lifts, and answers a refusal by its code, never its wording. */
export async function setSuspension(id: string, suspended: boolean): Promise<SetSuspensionResult> {
  try {
    await apiFetch<unknown>(`/admin/users/${encodeURIComponent(id)}/suspension`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ suspended }),
    });
    return { kind: "changed" };
  } catch (error) {
    if (!(error instanceof ApiError)) return { kind: "unknown" };
    if (error.status === 409 && error.code === "CANNOT_SUSPEND_YOURSELF") return { kind: "yourself" };
    if (error.status === 404 && error.code === "USER_NOT_FOUND") return { kind: "notFound" };
    // A strategy or a seat appeared while the suspension took its locks: nothing was written.
    if (error.status === 409 && error.code === "ACCOUNT_CHANGED") return { kind: "accountChanged" };
    return { kind: "unknown" };
  }
}

/** The change as a mutation; the list is read again whatever the answer, so the row shows the server's state. */
export function useSetSuspension() {
  const queryClient = useQueryClient();
  return useMutation<SetSuspensionResult, Error, { id: string; suspended: boolean }>({
    mutationFn: ({ id, suspended }) => setSuspension(id, suspended),
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });
}

export function useAdminUsers() {
  return useQuery({ queryKey: ["admin-users"], queryFn: fetchAdminUsers });
}
