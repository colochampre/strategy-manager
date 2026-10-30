import { useTranslation } from "react-i18next";

import { VisibilityField } from "@/features/strategies/VisibilityField";
import { ApiError } from "@/shared/api/client";
import { useSetStrategyVisibility } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";

interface VisibilityControlProps {
  strategy: Strategy;
}

/** The text of a refused or failed change: the status (and the archived code) decides, never the server's wording. */
function refusal(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409 && error.code === "STRATEGY_ARCHIVED") return "strategies.detail.share.archived";
    if (error.status === 404) return "strategies.detail.share.gone";
  }
  return "strategies.visibility.saveFailed";
}

/**
 * The visibility of a strategy on its page: the stored value, changed by choosing the other one. The change is
 * sent at once, with nothing else in the body. An archived strategy never changes again, so its select is
 * unavailable, as its enable switch is; a refused change says so and the page reads the stored value again.
 */
export function VisibilityControl({ strategy }: VisibilityControlProps) {
  const { t } = useTranslation();
  const change = useSetStrategyVisibility(strategy.id);

  return (
    <div className="flex flex-col gap-2">
      <VisibilityField
        value={strategy.visibility}
        onChange={(visibility) => {
          if (strategy.archived_at === null) change.mutate(visibility);
        }}
        disabled={strategy.archived_at !== null || change.isPending}
        selectClass="min-h-11 rounded-md border border-rule bg-ground px-3 text-sm text-ink disabled:opacity-50"
      />
      {change.status === "error" && (
        <p role="alert" className="text-xs text-loss">
          {t(refusal(change.error))}
        </p>
      )}
    </div>
  );
}
