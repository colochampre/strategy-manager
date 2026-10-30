import { type KeyboardEvent, type SyntheticEvent, useId, useLayoutEffect, useRef } from "react";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/shared/api/client";

interface RegenerateSecretDialogProps {
  pending: boolean;
  /** The mutation's error, if any: an `ApiError` with a status and maybe a code, or anything else. */
  error: unknown;
  onConfirm: () => void;
  onCancel: () => void;
}

/** The text of a refusal: the status and the archived code decide, never the server's wording. */
function refusalKey(error: ApiError): string {
  if (error.status === 409 && error.code === "STRATEGY_ARCHIVED") return "strategies.detail.share.archived";
  if (error.status === 404) return "strategies.detail.share.gone";
  return "strategies.webhook.regenerateFailed";
}

/**
 * Confirms a regeneration, which cannot be undone: the old secret stops working at once, so every alert that
 * still carries it is refused. Confirm is its own button, so nothing is sent by the click that opened the
 * dialog; cancel and Escape send nothing. A refusal is rendered inside and the dialog stays open.
 *
 * A native `<dialog>` upgraded to a modal where the browser supports it, with Escape and the browser's own
 * `cancel` event routed to the same handler, as `ArchiveDialog` does.
 */
export function RegenerateSecretDialog({ pending, error, onConfirm, onCancel }: RegenerateSecretDialogProps) {
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

  const refusal =
    error === null || error === undefined
      ? null
      : error instanceof ApiError
        ? refusalKey(error)
        : "strategies.webhook.regenerateFailed";

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
          {t("strategies.webhook.regenerateTitle")}
        </h2>
        <p className="text-xs text-ink-2">{t("strategies.webhook.regenerateBody")}</p>

        {refusal !== null && (
          <p role="alert" className="text-sm text-loss">
            {t(refusal)}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={cancel}
            disabled={pending}
            className="rounded-md border border-rule px-3 py-1.5 text-sm text-ink-2 hover:bg-panel-2 disabled:opacity-50"
          >
            {t("strategies.webhook.regenerateCancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className="inline-flex items-center gap-1.5 rounded-md bg-loss px-3 py-1.5 text-sm font-medium text-ink hover:opacity-90 disabled:opacity-50"
          >
            <RefreshCw aria-hidden="true" className="size-4 shrink-0" />
            {pending ? t("strategies.webhook.regenerating") : t("strategies.webhook.regenerateConfirm")}
          </button>
        </div>
      </div>
    </dialog>
  );
}
