import { type KeyboardEvent, type SyntheticEvent, useId, useLayoutEffect, useRef } from "react";
import { LogOut } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/shared/api/client";

interface LeaveDialogProps {
  name: string;
  pending: boolean;
  /** The mutation's error, if any. */
  error: unknown;
  onConfirm: () => void;
  onCancel: () => void;
}

/** The text of a refused leave: the status and the code decide, never the server's wording. */
function refusalText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "AUTHOR_CANNOT_LEAVE") return "strategies.leave.errors.author";
    if (error.code === "SUBSCRIPTION_NOT_ACTIVE") return "strategies.leave.errors.notActive";
    if (error.status === 404) return "strategies.leave.errors.gone";
  }
  return "strategies.leave.errors.generic";
}

/**
 * Confirms leaving a strategy, which may not be undone: a subscriber who leaves a private one cannot come back
 * while it stays private (decision 21). Confirm is its own button, so the click that opened the dialog sends
 * nothing. A native `<dialog>`, with Escape and the browser's `cancel` event routed to one handler, as
 * `ArchiveDialog` does.
 */
export function LeaveDialog({ name, pending, error, onConfirm, onCancel }: LeaveDialogProps) {
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
          {t("strategies.leave.confirmTitle", { name })}
        </h2>
        <p className="text-xs text-ink-2">{t("strategies.leave.confirmBody", { name })}</p>
        <p className="text-xs text-ink-2">{t("strategies.leave.privateNote")}</p>

        {error !== null && error !== undefined && (
          <p role="alert" className="text-sm text-loss">
            {t(refusalText(error))}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={cancel}
            disabled={pending}
            className="min-h-11 rounded-md border border-rule px-3 text-sm text-ink-2 hover:bg-panel-2 disabled:opacity-50"
          >
            {t("strategies.leave.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-md bg-loss px-3 text-sm font-medium text-ink hover:opacity-90 disabled:opacity-50"
          >
            <LogOut aria-hidden="true" className="size-4 shrink-0" />
            {pending ? t("strategies.leave.pending") : t("strategies.leave.confirm")}
          </button>
        </div>
      </div>
    </dialog>
  );
}
