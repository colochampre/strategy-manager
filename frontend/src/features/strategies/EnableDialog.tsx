import { type KeyboardEvent, type ReactNode, type SyntheticEvent, useId, useLayoutEffect, useRef, useState } from "react";
import { Power, PowerOff } from "lucide-react";
import { useTranslation } from "react-i18next";

import { OpenPositionReasonList, openPositionReasons } from "@/features/strategies/openPositionReasons";
import { ApiError } from "@/shared/api/client";
import { useSetStrategyEnabled } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";
import { GAIN_OUTLINE } from "@/shared/ui/button-styles";

interface EnableDialogProps {
  name: string;
  /** What the question asks for: true to enable the strategy, false to disable it. */
  enabling: boolean;
  pending: boolean;
  /** The mutation's error, if any: an `ApiError` with a refusal code, or anything else. */
  error: unknown;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Asks before a strategy is enabled or disabled, so a stray click on the switch changes nothing (owner,
 * 2026-11-06). Disabling stops every opening of the strategy, for everyone trading it; a close is never gated by
 * it, so a position already open still closes. A native `<dialog>`, with Escape and the browser's `cancel` event
 * routed to one handler, as `LeaveDialog` does; it holds while the change is on its way.
 */
function EnableDialog({ name, enabling, pending, error, onConfirm, onCancel }: EnableDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const Icon = enabling ? Power : PowerOff;

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null) return undefined;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    return () => {
      if (typeof dialog.close === "function") dialog.close();
    };
  }, []);

  const cancel = () => {
    if (!pending) onCancel();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    cancel();
  };

  const handleCancelEvent = (event: SyntheticEvent<HTMLDialogElement>) => {
    event.preventDefault();
    cancel();
  };

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      onKeyDown={handleKeyDown}
      onCancel={handleCancelEvent}
      className="fixed inset-0 m-auto w-full max-w-lg rounded-lg border border-rule bg-panel p-0 text-ink backdrop:bg-ground/80"
    >
      <div className="flex flex-col gap-4 p-6">
        <h2 id={titleId} className="text-sm font-semibold text-ink">
          {t(enabling ? "strategies.enableDialog.enableTitle" : "strategies.enableDialog.disableTitle", { name })}
        </h2>
        <p className="text-xs text-ink-2">
          {t(enabling ? "strategies.enableDialog.enableBody" : "strategies.enableDialog.disableBody", { name })}
        </p>
        {error !== null && error !== undefined && (
          <div role="alert" className="flex flex-col gap-1 text-sm text-loss">
            {error instanceof ApiError && error.code === "OPEN_POSITION" ? (
              <>
                <p>{t("strategies.enableDialog.openPosition")}</p>
                <OpenPositionReasonList reasons={openPositionReasons(error)} />
              </>
            ) : (
              <p>{t("strategies.row.toggleError")}</p>
            )}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={cancel}
            disabled={pending}
            className="min-h-11 rounded-lg border border-rule px-3 text-sm text-ink-2 hover:bg-panel-2 disabled:opacity-50"
          >
            {t("strategies.enableDialog.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className={`inline-flex min-h-11 items-center gap-1.5 rounded-lg px-3 text-sm ${GAIN_OUTLINE} disabled:opacity-50`}
          >
            <Icon aria-hidden="true" className="size-4 shrink-0" />
            {pending
              ? t("strategies.enableDialog.pending")
              : t(enabling ? "strategies.enableDialog.enable" : "strategies.enableDialog.disable")}
          </button>
        </div>
      </div>
    </dialog>
  );
}

interface EnableQuestion {
  /** Opens the question for the strategy's opposite state. */
  ask: () => void;
  /** Whether the question is open or the change is on its way: the control that asks is unavailable meanwhile. */
  busy: boolean;
  /** The question while it is open, or null. */
  dialog: ReactNode;
}

/**
 * The one way the panel enables or disables a strategy: the switch on My strategies and the button on its page
 * both ask here first. The state asked for is fixed when the question opens, so a read that lands meanwhile cannot
 * turn "disable" into "enable" under the reader's click.
 */
export function useEnableQuestion(strategy: Strategy): EnableQuestion {
  const toggle = useSetStrategyEnabled(strategy.id);
  const [target, setTarget] = useState<boolean | null>(null);

  const ask = () => {
    toggle.reset();
    setTarget(!strategy.enabled);
  };

  const dialog =
    target === null ? null : (
      <EnableDialog
        name={strategy.name}
        enabling={target}
        pending={toggle.isPending}
        error={toggle.error}
        onConfirm={() => toggle.mutate(target, { onSuccess: () => setTarget(null) })}
        onCancel={() => setTarget(null)}
      />
    );

  return { ask, busy: toggle.isPending, dialog };
}
