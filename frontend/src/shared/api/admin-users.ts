import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";
import type { Mode } from "@/shared/api/me";

/**
 * One user as the admin sees them (decision 8): their state, and no amount and no performance. An exchange in
 * `exchanges_with_no_key` has an enabled pool and no active key, which is what the database can say of a degraded
 * one.
 */
export interface AdminUser {
  email: string;
  display_name: string | null;
  mode: Mode;
  exchanges_with_key: string[];
  exchanges_with_no_key: string[];
  subscriptions: number;
  open_positions: number;
  last_seen_at: string;
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

/** An `AdminUserBody`, field by field. A null name is a user who has not chosen one, so it is an answer; a missing one is not. */
function isAdminUser(value: unknown): value is AdminUser {
  if (!isRecord(value)) return false;
  return (
    typeof value.email === "string" &&
    (value.display_name === null || typeof value.display_name === "string") &&
    (value.mode === "LIVE" || value.mode === "SIMULATION") &&
    isTextList(value.exchanges_with_key) &&
    isTextList(value.exchanges_with_no_key) &&
    isCount(value.subscriptions) &&
    isCount(value.open_positions) &&
    typeof value.last_seen_at === "string"
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

export function useAdminUsers() {
  return useQuery({ queryKey: ["admin-users"], queryFn: fetchAdminUsers });
}
