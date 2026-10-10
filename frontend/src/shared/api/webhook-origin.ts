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
 * `GET /api/webhook-origin`: the origin TradingView posts to, or null when none is usable. A body without
 * an `origin` key, or whose `origin` is neither null nor a string, reads as an error; a string that is not
 * a serialised origin reads as no host. The origin is only displayed and copied: it is never requested.
 */
export async function fetchWebhookOrigin(): Promise<string | null> {
  const body = await apiFetch<unknown>("/webhook-origin");
  const origin = typeof body === "object" && body !== null ? (body as Record<string, unknown>).origin : undefined;
  if (origin === null) return null;
  if (typeof origin !== "string") {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /webhook-origin: expected an origin or null",
    });
  }
  return acceptedOrigin(origin);
}

/** Read when the block mounts, which is when it is opened. An older API's 404 reads as an error. */
export function useWebhookOrigin() {
  return useQuery({ queryKey: WEBHOOK_ORIGIN_QUERY_KEY, queryFn: fetchWebhookOrigin });
}
