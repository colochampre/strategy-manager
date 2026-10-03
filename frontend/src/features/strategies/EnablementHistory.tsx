import { useTranslation } from "react-i18next";

import { dayText } from "@/features/strategies/format";
import { useStrategyEvents } from "@/shared/api/strategies";

interface EnablementHistoryProps {
  strategyId: string;
}

/**
 * Every enable and disable of the strategy, newest first (the server answers
 * oldest first). The one `BASELINE` row was written by a migration for a
 * strategy that was already enabled, so its date is when the history began, not
 * when the strategy was enabled, and the row says so.
 */
export function EnablementHistory({ strategyId }: EnablementHistoryProps) {
  const { t, i18n } = useTranslation();
  const events = useStrategyEvents(strategyId);
  const locale = i18n.resolvedLanguage ?? "en";
  const title = t("strategies.detail.history.title");

  let body;
  if (events.status === "error") {
    body = (
      <p role="alert" className="text-xs text-loss">
        {t("strategies.detail.history.error")}
      </p>
    );
  } else if (events.status === "success" && events.data.length === 0) {
    body = <p className="text-xs text-ink-3">{t("strategies.detail.history.empty")}</p>;
  } else if (events.status === "success") {
    body = (
      // A long history scrolls inside its own box instead of pushing the page down; focusable so the keyboard can scroll it.
      <ul
        aria-label={title}
        tabIndex={0}
        className="flex max-h-96 flex-col gap-1 overflow-y-auto font-mono text-xs text-ink-2"
      >
        {[...events.data].reverse().map((event) => {
          const state = t(event.enabled ? "strategies.detail.history.enabled" : "strategies.detail.history.disabled");
          const baseline = event.origin === "BASELINE" ? ` · ${t("strategies.detail.history.baseline")}` : "";
          return <li key={`${event.occurred_at}-${event.enabled}`}>{`${state} · ${dayText(event.occurred_at, locale)}${baseline}`}</li>;
        })}
      </ul>
    );
  }

  return (
    <section className="flex flex-col gap-2">
      <h2 className="font-display text-base font-semibold text-ink">{title}</h2>
      {body}
    </section>
  );
}
