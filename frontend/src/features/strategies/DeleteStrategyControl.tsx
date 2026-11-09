import { useId, useState } from "react";
import { Trash } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { DeleteStrategyDialog } from "@/features/strategies/DeleteStrategyDialog";
import { useDeleteStrategy } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";
import { IconButton } from "@/shared/ui/IconButton";

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
    deletion.mutate(undefined, { onSuccess: () => void navigate("/strategies/authored", { replace: true }) });
  };

  return (
    <section className="flex flex-col gap-2 border-t border-rule pt-4">
      <h2 className="text-sm font-semibold text-ink">{t("strategies.delete.title")}</h2>
      <p className="text-xs text-ink-3">{t("strategies.delete.description")}</p>
      <div className="flex items-center gap-3">
        <IconButton
          icon={Trash}
          label={t("strategies.delete.button")}
          disabled={strategy.enabled}
          describedBy={strategy.enabled ? hintId : undefined}
          onClick={() => setOpen(true)}
          tone="danger"
        />
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
