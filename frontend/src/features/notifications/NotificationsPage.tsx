import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { storeLastOpened } from "@/features/notifications/lastOpened";
import { KIND_LOOK, NotificationRow } from "@/features/notifications/NotificationRow";
import { type NotificationItem, type NotificationKind, useNotifications } from "@/shared/api/notifications";
import { useMe } from "@/shared/api/me";
import { cn } from "@/shared/lib/cn";
import { PageHeader } from "@/shared/ui/PageHeader";
import { PAGER_BUTTON } from "@/shared/ui/table-styles";

const DAY_MS = 24 * 3600 * 1000;

/** The chips, in the prototype's order; Discrepancies is the admin's alone. */
const CHIP_KINDS: readonly NotificationKind[] = ["OPERATION", "SAFETY", "NOTICE", "DISCREPANCY"];

/** The UTC calendar day of an instant, as `YYYY-MM-DD`; an instant that cannot be read is its own day. */
function dayKeyOf(iso: string): string {
  const instant = new Date(iso);
  return Number.isNaN(instant.getTime()) ? iso : instant.toISOString().slice(0, 10);
}

/** Consecutive items of one UTC day, newest first as the server answers. */
function byDay(items: readonly NotificationItem[]): Array<{ day: string; first: string; items: NotificationItem[] }> {
  const days: Array<{ day: string; first: string; items: NotificationItem[] }> = [];
  for (const item of items) {
    const day = dayKeyOf(item.occurred_at);
    const last = days.at(-1);
    if (last?.day === day) last.items.push(item);
    else days.push({ day, first: item.occurred_at, items: [item] });
  }
  return days;
}

/**
 * A day as ex5 heads it, in UTC like every instant of the panel: day and month in words ("November 24",
 * "24 de noviembre"), and the year only when it is not the current one.
 */
function dayText(iso: string, locale: string, now: number): string {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return iso;
  const sameYear = instant.getUTCFullYear() === new Date(now).getUTCFullYear();
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "long",
    ...(sameYear ? {} : { year: "numeric" }),
    timeZone: "UTC",
  }).format(instant);
}

function DayCard({ day, first, items }: { day: string; first: string; items: NotificationItem[] }) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const now = Date.now();
  const date = dayText(first, i18n.resolvedLanguage ?? "en", now);
  let heading = date;
  if (day === dayKeyOf(new Date(now).toISOString())) heading = t("notifications.today", { date });
  else if (day === dayKeyOf(new Date(now - DAY_MS).toISOString())) heading = t("notifications.yesterday", { date });
  return (
    <div>
      <h2 id={headingId} className="mb-2.5 mt-6 font-display text-[13px] font-semibold text-ink-2">
        {heading}
      </h2>
      <ul aria-labelledby={headingId} className="overflow-hidden rounded-[10px] border border-rule bg-panel">
        {items.map((item) => (
          <NotificationRow key={item.id} item={item} />
        ))}
      </ul>
    </div>
  );
}

function Chips({ kind, admin, onChange }: { kind: NotificationKind | null; admin: boolean; onChange: (next: NotificationKind | null) => void }) {
  const { t } = useTranslation();
  const chip = "inline-flex h-[34px] items-center gap-2 rounded-[17px] border px-3.5 text-[13px]";
  const on = "border-rule-strong bg-panel-2 text-ink";
  const off = "border-rule bg-panel text-ink-2 hover:bg-panel-2";
  return (
    <div role="group" aria-label={t("notifications.filters")} className="mt-1 flex flex-wrap gap-2.5">
      <button type="button" aria-pressed={kind === null} onClick={() => onChange(null)} className={cn(chip, kind === null ? on : off)}>
        {t("notifications.chip.all")}
      </button>
      {CHIP_KINDS.filter((candidate) => candidate !== "DISCREPANCY" || admin).map((candidate) => (
        <button
          key={candidate}
          type="button"
          aria-pressed={kind === candidate}
          onClick={() => onChange(candidate)}
          className={cn(chip, kind === candidate ? on : off)}
        >
          <i aria-hidden="true" className={cn("size-2 rounded-full", KIND_LOOK[candidate].dot)} />
          {t(`notifications.chip.${candidate}`)}
        </button>
      ))}
    </div>
  );
}

function Feed({ kind }: { kind: NotificationKind | null }) {
  const { t } = useTranslation();
  const feed = useNotifications(kind);

  if (feed.isPending) {
    return (
      <p role="status" className="mt-6 text-sm text-ink-3">
        {t("notifications.loading")}
      </p>
    );
  }
  if (feed.data === undefined) {
    return (
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <p role="alert" className="text-sm text-loss">
          {t("notifications.error")}
        </p>
        <button
          type="button"
          onClick={() => void feed.refetch()}
          className="min-h-11 rounded-lg border border-rule px-3.5 text-sm text-ink hover:bg-panel-2"
        >
          {t("notifications.retry")}
        </button>
      </div>
    );
  }
  const items = feed.data.pages.flatMap((page) => page.items);
  if (items.length === 0) return <p className="mt-6 text-sm text-ink-3">{t("notifications.empty")}</p>;

  return (
    <>
      {byDay(items).map((day) => (
        <DayCard key={day.day} day={day.day} first={day.first} items={day.items} />
      ))}
      {feed.isError && (
        <p role="alert" className="mt-4 text-sm text-loss">
          {t("notifications.moreError")}
        </p>
      )}
      {feed.hasNextPage && (
        <div className="mt-4 flex justify-center">
          <button type="button" disabled={feed.isFetchingNextPage} onClick={() => void feed.fetchNextPage()} className={PAGER_BUTTON}>
            {t("notifications.showMore")}
          </button>
        </div>
      )}
    </>
  );
}

/**
 * The user's operations, the safety events and the notices of their account in one feed, newest first, a card per
 * day (S6, RD.5; ex5). The chips send the kind. Opening the page stores the instant: the bell lights for what arrives
 * after it.
 */
export function NotificationsPage() {
  const { t } = useTranslation();
  const me = useMe();
  const user = me.data?.email ?? null;
  const [kind, setKind] = useState<NotificationKind | null>(null);
  useEffect(() => {
    if (user !== null) storeLastOpened(user);
  }, [user]);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader crumbs={[{ label: t("nav.notifications") }]} title={t("nav.notifications")} subtitle={t("notifications.intro")} />
      <Chips kind={kind} admin={me.data?.isAdmin === true} onChange={setKind} />
      <Feed kind={kind} />
    </div>
  );
}
