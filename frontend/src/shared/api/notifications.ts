import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";

/** Items a page of the feed holds (RD.5). */
export const NOTIFICATIONS_PAGE_SIZE = 30;

export type NotificationKind = "OPERATION" | "SAFETY" | "NOTICE" | "DISCREPANCY";

/** The kinds in the order the server lists the unseen ones: the most important first. */
export const NOTIFICATION_KINDS: readonly NotificationKind[] = ["SAFETY", "DISCREPANCY", "NOTICE", "OPERATION"];

/**
 * One item of `GET /notifications`. `event` and `reason` are typed as text: a value this build does not know is
 * told with a generic line, never refused. Any of the strategy, market and figure fields is null where its source
 * has none.
 */
export interface NotificationItem {
  id: string;
  kind: NotificationKind;
  event: string;
  occurred_at: string;
  reason: string | null;
  strategy_id: string | null;
  strategy_name: string | null;
  exchange: string | null;
  venue: string | null;
  pair: string | null;
  side: "LONG" | "SHORT" | null;
  rehearsal: boolean;
  currency: string | null;
  entry_price: string | null;
  exit_price: string | null;
  pnl: string | null;
  leverage: string | null;
  close_cause: string | null;
  /** Every value is a string; which keys exist depends on the reason, and a missing one is tolerated. */
  detail: Record<string, string>;
}

export interface NotificationsPage {
  items: NotificationItem[];
  next_cursor: string | null;
}

export interface NotificationsQuery {
  kind: NotificationKind | null;
  cursor: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isText(value: unknown): value is string {
  return typeof value === "string";
}

function isTextOrNull(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isKind(value: unknown): value is NotificationKind {
  return typeof value === "string" && (NOTIFICATION_KINDS as readonly string[]).includes(value);
}

function isDetail(value: unknown): value is Record<string, string> {
  return isRecord(value) && Object.values(value).every(isText);
}

function isItem(value: unknown): value is NotificationItem {
  return (
    isRecord(value) &&
    isText(value.id) &&
    isKind(value.kind) &&
    isText(value.event) &&
    isText(value.occurred_at) &&
    isTextOrNull(value.reason) &&
    isTextOrNull(value.strategy_id) &&
    isTextOrNull(value.strategy_name) &&
    isTextOrNull(value.exchange) &&
    isTextOrNull(value.venue) &&
    isTextOrNull(value.pair) &&
    (value.side === null || value.side === "LONG" || value.side === "SHORT") &&
    typeof value.rehearsal === "boolean" &&
    isTextOrNull(value.currency) &&
    isTextOrNull(value.entry_price) &&
    isTextOrNull(value.exit_price) &&
    isTextOrNull(value.pnl) &&
    isTextOrNull(value.leverage) &&
    isTextOrNull(value.close_cause) &&
    isDetail(value.detail)
  );
}

function isPage(value: unknown): value is NotificationsPage {
  return isRecord(value) && Array.isArray(value.items) && value.items.every(isItem) && isTextOrNull(value.next_cursor);
}

function isUnseen(value: unknown): value is { kinds: NotificationKind[] } {
  return isRecord(value) && Array.isArray(value.kinds) && value.kinds.every(isKind);
}

/**
 * `GET /api/notifications`: a page of the signed-in user's feed, newest first. The cursor and the kind are sent only
 * when set. A body that is not a page throws, because an empty feed would read as "nothing happened" for a read that
 * simply failed.
 */
export async function fetchNotifications(query: NotificationsQuery): Promise<NotificationsPage> {
  const params = new URLSearchParams({ limit: String(NOTIFICATIONS_PAGE_SIZE) });
  if (query.cursor !== null) params.set("cursor", query.cursor);
  if (query.kind !== null) params.set("kind", query.kind);
  const body = await apiFetch<unknown>(`/notifications?${params}`);
  if (!isPage(body)) {
    throw new ApiError(200, { detail: "Unexpected response shape from GET /notifications: expected a page of items" });
  }
  return body;
}

/** `GET /api/notifications/unseen`: the kinds of what happened after `since`, most important first. */
export async function fetchUnseen(since: string): Promise<NotificationKind[]> {
  const body = await apiFetch<unknown>(`/notifications/unseen?${new URLSearchParams({ since })}`);
  if (!isUnseen(body)) {
    throw new ApiError(200, { detail: "Unexpected response shape from GET /notifications/unseen: expected kinds" });
  }
  return body.kinds;
}

export function notificationsKey(kind: NotificationKind | null) {
  return ["notifications", "feed", kind] as const;
}

export function unseenKey(since: string) {
  return ["notifications", "unseen", since] as const;
}

const FEED_STALE_MS = 30_000;

/** The feed, a page at a time: "Show more" asks for the next cursor. */
export function useNotifications(kind: NotificationKind | null) {
  return useInfiniteQuery({
    queryKey: notificationsKey(kind),
    queryFn: ({ pageParam }) => fetchNotifications({ kind, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    staleTime: FEED_STALE_MS,
  });
}

/** How often the bell asks what arrived since the user last opened the page. */
export const UNSEEN_REFRESH_MS = 60_000;

/** The bell's read. Off until there is an instant to ask since. */
export function useUnseen(since: string | null, enabled = true) {
  return useQuery({
    queryKey: unseenKey(since ?? ""),
    queryFn: () => fetchUnseen(since ?? ""),
    enabled: enabled && since !== null,
    staleTime: UNSEEN_REFRESH_MS,
    refetchInterval: UNSEEN_REFRESH_MS,
  });
}
