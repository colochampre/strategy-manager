import { Power, PowerOff } from "lucide-react";
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
  const Icon = strategy.enabled ? PowerOff : Power;

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        disabled={strategy.archived_at !== null || toggle.isPending}
        onClick={() => toggle.mutate(!strategy.enabled)}
        className="inline-flex min-h-11 items-center gap-1.5 rounded-md border border-rule px-3 text-sm text-ink hover:bg-panel-2 disabled:opacity-50"
      >
        <Icon aria-hidden="true" className="size-4 shrink-0" />
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
