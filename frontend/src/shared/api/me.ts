import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/shared/api/client";

/**
 * Who is signed in (multi-user design AD1 and AD11). Cloudflare Access signs
 * the person in before the page loads; the API verifies the assertion and
 * answers `GET /api/me`. `dryRun` is the server's emergency brake (`.env`
 * `DRY_RUN`), the same value `/health` publishes.
 */
export interface Me {
  email: string;
  isAdmin: boolean;
  dryRun: boolean;
}

interface MeWire {
  email?: unknown;
  is_admin?: unknown;
  dry_run?: unknown;
}

/**
 * Anything but a string e-mail and two booleans is an error: a malformed answer
 * must never be readable as "this is the admin".
 */
export async function fetchMe(): Promise<Me> {
  const body = await apiFetch<MeWire | null>("/me");
  const email = body?.email;
  const isAdmin = body?.is_admin;
  const dryRun = body?.dry_run;
  if (typeof email !== "string" || typeof isAdmin !== "boolean" || typeof dryRun !== "boolean") {
    throw new Error("Unexpected response shape from GET /api/me");
  }
  return { email, isAdmin, dryRun };
}

const ME_STALE_MS = 60_000;

/** Query key `['me']`. Fresh for a minute: who is signed in does not change under a page. */
export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: ME_STALE_MS });
}
