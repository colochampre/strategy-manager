import { useTranslation } from "react-i18next";

import { useSetStrategyEnabled } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";

interface EnableToggleProps {
  strategy: Strategy;
}

/**
 * Enables or disables the strategy. An archived strategy never changes again,
 * so its button is unavailable. A refused or failed change says so instead of
 * silently snapping back; the page then reads the stored state again.
 */
export function EnableToggle({ strategy }: EnableToggleProps) {
  const { t } = useTranslation();
  const toggle = useSetStrategyEnabled(strategy.id);

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        disabled={strategy.archived_at !== null || toggle.isPending}
        onClick={() => toggle.mutate(!strategy.enabled)}
        className="min-h-11 rounded-md border border-rule px-3 text-sm text-ink hover:bg-panel-2 disabled:opacity-50"
      >
        {strategy.enabled ? t("strategies.detail.disable") : t("strategies.detail.enable")}
      </button>
      {toggle.status === "error" && (
        <p role="alert" className="text-xs text-loss">
          {t("strategies.row.toggleError")}
        </p>
      )}
    </div>
  );
}
