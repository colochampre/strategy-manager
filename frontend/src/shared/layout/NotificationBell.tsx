import { Bell } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { storeLastOpened, useLastOpened } from "@/features/notifications/lastOpened";
import { useMe } from "@/shared/api/me";
import { type NotificationKind, useUnseen } from "@/shared/api/notifications";
import { cn } from "@/shared/lib/cn";

const DOT_TONE: Readonly<Record<NotificationKind, string>> = {
  OPERATION: "bg-notif-operation",
  SAFETY: "bg-notif-safety",
  DISCREPANCY: "bg-notif-discrepancy",
  NOTICE: "bg-notif-notice",
};

/** An Operation alone gives the dot and nothing more: the shake is for what asks something of the user (L59). */
const SHAKING_KINDS: readonly NotificationKind[] = ["SAFETY", "DISCREPANCY", "NOTICE"];

/**
 * The bell of the top row, a link to Notifications. It carries a dot, in the colour of the first kind the server
 * lists, when anything arrived after the user last opened the page; with nothing stored the first read stores now, so
 * history alone lights nothing. Safety, Discrepancy and Notice also shake it, 0.6 s on arrival and every 30 s, but
 * never under `prefers-reduced-motion` (`motion-safe:`). Opening the page stores a new instant and the dot goes.
 */
export function NotificationBell({ className }: { className: string }) {
  const { t } = useTranslation();
  const user = useMe().data?.email ?? null;
  const since = useLastOpened(user);
  useEffect(() => {
    if (user !== null && since === null) storeLastOpened(user);
  }, [user, since]);
  const unseen = useUnseen(since);
  const kinds = unseen.data ?? [];
  const first = kinds[0];
  const shakes = kinds.some((kind) => SHAKING_KINDS.includes(kind));

  return (
    <Link
      to="/notifications"
      aria-label={t(first === undefined ? "notifications.bell.label" : "notifications.bell.new")}
      className={cn(className, "relative")}
    >
      <Bell aria-hidden="true" className={cn("size-4 origin-[50%_12%]", shakes && "motion-safe:animate-bell-ring")} />
      {first !== undefined && (
        <i
          aria-hidden="true"
          data-testid="bell-dot"
          data-kind={first}
          className={cn("absolute right-1.5 top-1.5 size-2 rounded-full ring-2 ring-panel", DOT_TONE[first])}
        />
      )}
    </Link>
  );
}
