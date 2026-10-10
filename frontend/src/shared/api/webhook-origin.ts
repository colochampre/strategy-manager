import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";

/** `['webhook-origin']`: a fact about the deployment, under no strategy's key. */
export const WEBHOOK_ORIGIN_QUERY_KEY = ["webhook-origin"] as const;

/**
 * The value is used only if it is already a serialised origin: `new URL(value).origin === value`, the
 * browser's own definition. That one comparison rejects a path, a query, a fragment, a user, a trailing
 * slash, upper case and the scheme's default port. Anything else is no host (design § F).
 */
export function acceptedOrigin(value: string): string | null {
  try {
    return new URL(value).origin === value ? value : null;
  } catch {
    return null;
  }
}

/**
 * `GET /api/webhook-origin`: the origin TradingView posts to, or null when none is configured. A body
 * without an `origin` key, whose `origin` is neither null nor a string, or whose string is not a serialised
 * origin, reads as an error: the panel says the host could not be loaded, which is not what it says for a
 * served null. The origin is only displayed and copied: it is never requested.
 */
export async function fetchWebhookOrigin(): Promise<string | null> {
  const body = await apiFetch<unknown>("/webhook-origin");
  const origin = typeof body === "object" && body !== null ? (body as Record<string, unknown>).origin : undefined;
  if (origin === null) return null;
  const accepted = typeof origin === "string" ? acceptedOrigin(origin) : null;
  if (accepted === null) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /webhook-origin: expected an origin or null",
    });
  }
  return accepted;
}

/** Read when the block mounts, which is when it is opened. An older API's 404 reads as an error. */
export function useWebhookOrigin() {
  return useQuery({ queryKey: WEBHOOK_ORIGIN_QUERY_KEY, queryFn: fetchWebhookOrigin });
}
