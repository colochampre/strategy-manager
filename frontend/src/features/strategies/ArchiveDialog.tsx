import { type KeyboardEvent, type SyntheticEvent, useId, useLayoutEffect, useRef } from "react";
import { Archive } from "lucide-react";
import { useTranslation } from "react-i18next";

import { OpenPositionReasonList, openPositionReasons, type Reason } from "@/features/strategies/openPositionReasons";
import { ApiError } from "@/shared/api/client";

interface ArchiveDialogProps {
  name: string;
  pending: boolean;
  /** The mutation's error, if any: an `ApiError` with a refusal code, or anything else. */
  error: unknown;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Confirms an archive, which is terminal: the strategy is never enabled or
 * restored afterwards. Confirm is its own button, so nothing is sent by the one
 * click that opened the dialog; cancel and Escape send nothing. A refusal from
 * the server (still enabled, or an open position) is rendered inside, with the
 * reasons the server names.
 *
 * A native `<dialog>` upgraded to a modal where the browser supports it, with
 * Escape and the browser's own `cancel` event routed to the same handler, as
 * `DeleteStrategyDialog` does.
 */
export function ArchiveDialog({ name, pending, error, onConfirm, onCancel }: ArchiveDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);

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

  const refusal = (() => {
    if (error === null || error === undefined) return null;
    if (error instanceof ApiError && error.code === "STILL_ENABLED") {
      return { text: t("strategies.archive.errors.stillEnabled"), reasons: [] as Reason[] };
    }
    if (error instanceof ApiError && error.code === "OPEN_POSITION") {
      return { text: t("strategies.archive.errors.openPosition"), reasons: openPositionReasons(error) };
    }
    return { text: t("strategies.archive.errors.generic"), reasons: [] as Reason[] };
  })();

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      onKeyDown={handleKeyDown}
      onCancel={handleCancelEvent}
      className="fixed inset-0 m-auto w-full max-w-lg rounded-lg border border-rule bg-panel p-0 text-ink backdrop:bg-ground/80 motion-safe:animate-dialog-in"
    >
      <div className="flex flex-col gap-4 p-6">
        <h2 id={titleId} className="text-sm font-semibold text-ink">
          {t("strategies.archive.confirmTitle", { name })}
        </h2>
        <p className="text-xs text-ink-2">{t("strategies.archive.confirmBody", { name })}</p>

        {refusal !== null && (
          <div role="alert" className="flex flex-col gap-1 text-sm text-loss">
            <p>{refusal.text}</p>
            <OpenPositionReasonList reasons={refusal.reasons} />
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={cancel}
            disabled={pending}
            className="rounded-lg border border-rule px-3 py-1.5 text-sm text-ink-2 hover:bg-panel-2 disabled:opacity-50"
          >
            {t("strategies.archive.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className="inline-flex items-center gap-1.5 rounded-lg bg-loss px-3 py-1.5 text-sm font-medium text-ink hover:opacity-90 disabled:opacity-50"
          >
            <Archive aria-hidden="true" className="size-4 shrink-0" />
            {pending ? t("strategies.archive.pending") : t("strategies.archive.confirm")}
          </button>
        </div>
      </div>
    </dialog>
  );
}
