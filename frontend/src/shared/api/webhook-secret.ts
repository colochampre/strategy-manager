import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";

/**
 * The key carries no value: `['webhook-secret']`, never the secret itself, and
 * not under `['strategy', id]` or any other key a list refetch could touch.
 */
export const WEBHOOK_SECRET_QUERY_KEY = ["webhook-secret"] as const;

/**
 * `GET /api/webhook-secret`: the webhook's shared secret, answered only to an
 * explicit "Show secret" click (decision 23). A body that is not a non-empty
 * secret reads as an error, with a fixed message: the refusal never echoes the
 * body it refused, because that body is where the secret would be.
 */
export async function fetchWebhookSecret(): Promise<string> {
  const body = await apiFetch<unknown>("/webhook-secret");
  const secret = typeof body === "object" && body !== null ? (body as Record<string, unknown>).secret : undefined;
  if (typeof secret !== "string" || secret === "") {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /webhook-secret: expected a non-empty secret",
    });
  }
  return secret;
}

/**
 * Fetches only while `enabled` is true, and `WebhookMessage` makes it true only
 * on the "Show secret" click. Every other way a query asks again is off: no
 * retry (a failed read says so and waits for another click), no refetch on
 * window focus, reconnect or mount, and never stale. Whoever enables it must
 * evict `WEBHOOK_SECRET_QUERY_KEY` when it is done.
 */
export function useWebhookSecret(enabled: boolean) {
  return useQuery({
    queryKey: WEBHOOK_SECRET_QUERY_KEY,
    queryFn: fetchWebhookSecret,
    enabled,
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchOnMount: false,
  });
}
