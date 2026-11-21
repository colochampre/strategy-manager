import { useTranslation } from "react-i18next";

import type { SafetyEvent } from "@/shared/api/safetyEvents";
import { useSafetyEvents } from "@/shared/api/safetyEvents";
import { exchangeName } from "@/shared/exchanges/exchange-name";
import { dateTimeText, figureText } from "@/shared/lib/figure-text";

/** The kinds this build writes a sentence for; any other kind falls back to the neutral wording. */
const KNOWN_KINDS: readonly string[] = [
  "STOP_FIRED",
  "STOP_FAILED_CLOSED",
  "STRATEGY_STOPPED_CLOSED",
  "MANUAL_CLOSE",
  "OPENING_REFUSED_LEVERAGE_CAP",
  "OPENING_REFUSED_ACCOUNT_SUSPENDED",
  "OPENING_REFUSED_AUTHOR_SUSPENDED",
];

/** The detail keys each kind's sentence interpolates; a key the event lacks is written as "n/a", never "undefined". */
const DETAIL_KEYS: Record<string, readonly string[]> = {
  STOP_FIRED: ["quantity", "trigger_price"],
  STOP_FAILED_CLOSED: ["quantity", "price"],
  STRATEGY_STOPPED_CLOSED: ["quantity", "price"],
  MANUAL_CLOSE: ["quantity", "price"],
  OPENING_REFUSED_LEVERAGE_CAP: ["requested_leverage", "max_leverage", "stop_loss_pct"],
};

function EventRow({ event }: { event: SafetyEvent }) {
  const { t, i18n } = useTranslation();
  const known = KNOWN_KINDS.includes(event.kind);
  const missing = t("safetyEvents.detail.missing");
  const values: Record<string, string> = {};
  for (const key of DETAIL_KEYS[event.kind] ?? []) {
    const stored = event.detail[key];
    values[key] = stored === undefined ? missing : (figureText(stored) ?? stored);
  }

  return (
    <li className="flex flex-col gap-1 rounded-md border border-rule bg-panel px-4 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="font-display text-base font-semibold text-ink">
          {t(known ? `safetyEvents.kind.${event.kind}` : "safetyEvents.kind.unknown")}
        </p>
        <p className="font-mono text-xs text-ink-3">{dateTimeText(event.occurred_at, i18n.language)}</p>
      </div>
      <p className="min-w-0 break-words text-sm text-ink-2">
        <span className="text-ink">{event.strategy_name}</span>
        {` · ${event.symbol} · ${exchangeName(t, i18n, event.exchange)}`}
      </p>
      <p className="min-w-0 break-words text-sm text-ink-2">
        {known ? t(`safetyEvents.detail.${event.kind}`, values) : t("safetyEvents.detail.unknown")}
      </p>
    </li>
  );
}

function EventList() {
  const { t } = useTranslation();
  const events = useSafetyEvents();

  if (events.status === "pending") return <p className="text-sm text-ink-2">{t("safetyEvents.loading")}</p>;
  if (events.status === "error") {
    return (
      <p role="alert" className="text-sm text-loss">
        {t("safetyEvents.error")}
      </p>
    );
  }
  if (events.data.events.length === 0) return <p className="text-sm text-ink-3">{t("safetyEvents.empty")}</p>;

  return (
    // A long history scrolls inside its own box; focusable so the keyboard can scroll it.
    <ul
      aria-label={t("safetyEvents.listLabel")}
      tabIndex={0}
      className="flex max-h-[70vh] flex-col gap-4 overflow-y-auto"
    >
      {events.data.events.map((event) => (
        <EventRow key={event.id} event={event} />
      ))}
    </ul>
  );
}

/**
 * What the safety net did for the signed-in user (SS.10): stops that fired, closes made for them and openings
 * refused, newest first as the server answers. Only their own events: the route is scoped to the user.
 */
export function SafetyEventsPage() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-2xl font-bold text-ink">{t("safetyEvents.title")}</h1>
      <p className="-mt-3 text-sm text-ink-2">{t("safetyEvents.intro")}</p>
      <EventList />
    </div>
  );
}
