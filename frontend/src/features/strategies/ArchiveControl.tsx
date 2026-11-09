import { useId, useState } from "react";
import { Archive } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ArchiveDialog } from "@/features/strategies/ArchiveDialog";
import { useArchiveStrategy } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import { DANGER_CONTROL } from "@/shared/ui/danger-control";
import { Tooltip } from "@/shared/ui/Tooltip";

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

  const button = (
    <button
      type="button"
      disabled={strategy.enabled}
      aria-describedby={strategy.enabled ? hintId : undefined}
      onClick={() => setOpen(true)}
      className={cn(DANGER_CONTROL, "w-full justify-center")}
    >
      <Archive aria-hidden="true" className="size-4 shrink-0" />
      {t("strategies.archive.button")}
    </button>
  );

  return (
    // Half of the row beside Disable (equal width). The reason Archive is unavailable is its tooltip: a disabled
    // button gets no pointer events and no focus, so the tip lives on a focusable wrapper; the same text, hidden,
    // is the button's description for assistive technology.
    <div className="min-w-0 flex-1">
      {strategy.enabled ? (
        <>
          <Tooltip text={t("strategies.archive.disabledHint")} describes={false} className="flex w-full">
            {button}
          </Tooltip>
          <span id={hintId} hidden>
            {t("strategies.archive.disabledHint")}
          </span>
        </>
      ) : (
        button
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
