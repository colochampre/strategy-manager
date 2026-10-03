import { useTranslation } from "react-i18next";

import { dayText } from "@/features/strategies/format";
import type { StrategyUptime } from "@/shared/api/types";

const DAY_SECONDS = 86_400;

interface UptimeSummaryProps {
  uptime: StrategyUptime;
}

/**
 * "Active X days since <first activation>" (decision 9). A baseline first
 * activation was written by the migration, so the true date is unknown and the
 * text says "at least". A strategy never enabled has no date and claims none.
 */
export function UptimeSummary({ uptime }: UptimeSummaryProps) {
  const { t, i18n } = useTranslation();
  if (uptime.first_enabled_at === null) return <span>{t("strategies.row.neverEnabled")}</span>;
  const count = Math.floor(uptime.seconds / DAY_SECONDS);
  const date = dayText(uptime.first_enabled_at, i18n.resolvedLanguage ?? "en");
  return <span>{t(uptime.baseline ? "strategies.detail.uptime.activeAtLeast" : "strategies.detail.uptime.active", { count, date })}</span>;
}
