import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { DeleteStrategyDialog } from "@/features/strategies/DeleteStrategyDialog";
import { useDeleteStrategy } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";

interface DeleteStrategyControlProps {
  strategy: Strategy;
}

/**
 * The "Delete strategy" block of a strategy's page: a short text, one button
 * and the confirmation it opens. The button is disabled while the strategy is
 * enabled (the server still decides); an archived strategy can be deleted.
 * A success, or a 404 (already gone), leaves for the list with `replace`, so
 * Back does not return to a page that no longer exists.
 */
export function DeleteStrategyControl({ strategy }: DeleteStrategyControlProps) {
  const { t } = useTranslation();
  const hintId = useId();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const deletion = useDeleteStrategy(strategy.id);

  const close = () => {
    deletion.reset();
    setOpen(false);
  };

  const confirm = () => {
    deletion.mutate(undefined, { onSuccess: () => void navigate("/strategies", { replace: true }) });
  };

  return (
    <section className="flex flex-col gap-2 border-t border-rule pt-4">
      <h2 className="text-sm font-semibold text-ink">{t("strategies.delete.title")}</h2>
      <p className="text-xs text-ink-3">{t("strategies.delete.description")}</p>
      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={strategy.enabled}
          aria-describedby={strategy.enabled ? hintId : undefined}
          onClick={() => setOpen(true)}
          className="rounded-md border border-loss px-3 py-1.5 text-sm text-loss hover:bg-panel-2 disabled:opacity-50"
        >
          {t("strategies.delete.button")}
        </button>
        {strategy.enabled && (
          <p id={hintId} className="text-xs text-ink-3">
            {t("strategies.delete.disabledHint")}
          </p>
        )}
      </div>
      {open && (
        <DeleteStrategyDialog
          name={strategy.name}
          pending={deletion.isPending}
          error={deletion.error}
          onConfirm={confirm}
          onCancel={close}
        />
      )}
    </section>
  );
}
