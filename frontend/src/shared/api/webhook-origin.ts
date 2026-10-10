import { useQuery } from "@tanstack/react-query";

/** `['webhook-origin']`: a fact about the deployment, under no strategy's key. */
export const WEBHOOK_ORIGIN_QUERY_KEY = ["webhook-origin"] as const;

/** STUB (12f.10.8 RED): accepts every text, until the GREEN keeps only a serialised origin. */
export function acceptedOrigin(value: string): string | null {
  return value;
}

/** STUB (12f.10.8 RED): answers no origin and sends nothing, until the GREEN reads `GET /webhook-origin`. */
export function fetchWebhookOrigin(): Promise<string | null> {
  return Promise.resolve(null);
}

export function useWebhookOrigin() {
  return useQuery({ queryKey: WEBHOOK_ORIGIN_QUERY_KEY, queryFn: fetchWebhookOrigin });
}
