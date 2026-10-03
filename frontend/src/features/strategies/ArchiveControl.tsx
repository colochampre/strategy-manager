import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { ArchiveDialog } from "@/features/strategies/ArchiveDialog";
import { useArchiveStrategy } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";

interface ArchiveControlProps {
  strategy: Strategy;
}

/**
 * The "Archive" button of a strategy's page and the confirmation it opens. The
 * button is unavailable while the strategy is enabled and says why (the server
 * still decides, and also refuses an open position). A strategy that is already
 * archived is not offered the control. A confirmed archive closes the dialog;
 * the refetch of the strategy then shows it archived.
 */
export function ArchiveControl({ strategy }: ArchiveControlProps) {
  const { t } = useTranslation();
  const hintId = useId();
  const [open, setOpen] = useState(false);
  const archive = useArchiveStrategy(strategy.id);

  if (strategy.archived_at !== null) return null;

  const close = () => {
    archive.reset();
    setOpen(false);
  };

  const confirm = () => {
    archive.mutate(undefined, { onSuccess: () => setOpen(false) });
  };

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        disabled={strategy.enabled}
        aria-describedby={strategy.enabled ? hintId : undefined}
        onClick={() => setOpen(true)}
        className="min-h-11 rounded-md border border-rule px-3 text-sm text-ink hover:bg-panel-2 disabled:text-ink-3 disabled:opacity-50"
      >
        {t("strategies.archive.button")}
      </button>
      {strategy.enabled && (
        <p id={hintId} className="text-xs text-ink-3">
          {t("strategies.archive.disabledHint")}
        </p>
      )}
      {open && (
        <ArchiveDialog
          name={strategy.name}
          pending={archive.isPending}
          error={archive.error}
          onConfirm={confirm}
          onCancel={close}
        />
      )}
    </div>
  );
}
