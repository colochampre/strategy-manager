import { useTranslation } from "react-i18next";
import { useParams } from "react-router";

/** Placeholder until PR 12. */
export function StrategyDetailPage() {
  const { t } = useTranslation();
  const { strategyId } = useParams();

  return (
    <div className="flex flex-col gap-2">
      <h1 className="font-display text-2xl font-bold text-ink">{t("strategies.detail.title")}</h1>
      <p className="font-mono text-xs text-ink-3">{strategyId}</p>
    </div>
  );
}
