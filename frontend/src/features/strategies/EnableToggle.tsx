import { Power, PowerOff } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useEnableQuestion } from "@/features/strategies/EnableDialog";
import type { Strategy } from "@/shared/api/types";

interface EnableToggleProps {
  strategy: Strategy;
}

/**
 * Enables or disables the strategy, after asking (`useEnableQuestion`). An archived strategy never changes again,
 * so its button is unavailable. A refused or failed change says so inside the question instead of silently
 * snapping back; the page then reads the stored state again.
 */
export function EnableToggle({ strategy }: EnableToggleProps) {
  const { t } = useTranslation();
  const question = useEnableQuestion(strategy);
  const Icon = strategy.enabled ? PowerOff : Power;

  return (
    // 1.6 shares of the row beside Archive's one, as the prototype draws it: at half the row "Disable strategy" breaks.
    <div className="min-w-0 flex-1 grow-[1.6]">
      <button
        type="button"
        disabled={strategy.archived_at !== null || question.busy}
        onClick={question.ask}
        className="inline-flex min-h-11 w-full items-center justify-center gap-1.5 rounded-lg border border-rule-strong bg-panel-2 px-3 text-sm font-medium text-ink hover:bg-ground disabled:opacity-50"
      >
        <Icon aria-hidden="true" className="size-4 shrink-0" />
        {strategy.enabled ? t("strategies.detail.disable") : t("strategies.detail.enable")}
      </button>
      {question.dialog}
    </div>
  );
}
