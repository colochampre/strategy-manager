import { type KeyboardEvent, type SyntheticEvent, useId, useLayoutEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import type { SetSuspensionResult } from "@/shared/api/admin-users";

interface SuspensionDialogProps {
  email: string;
  /** What the dialog asks for: suspending an account, or lifting its suspension. */
  suspending: boolean;
  pending: boolean;
  /** The last answer, if it was a refusal. */
  refusal: SetSuspensionResult | undefined;
  onConfirm: () => void;
  onCancel: () => void;
}

/** The text of a refusal: the kind decides, never the server's wording. */
function refusalKey(refusal: SetSuspensionResult | undefined): string | null {
  if (refusal === undefined || refusal.kind === "changed") return null;
  if (refusal.kind === "yourself") return "users.yourself";
  if (refusal.kind === "accountChanged") return "users.accountChanged";
  return "users.failed";
}

/**
 * Confirms suspending an account, or lifting it (public-site LS9). Confirm is its own button, so the click that
 * opened the dialog sends nothing. A native `<dialog>`, with Escape and the browser's `cancel` event routed to one
 * handler, as `LeaveDialog` does.
 */
export function SuspensionDialog({ email, suspending, pending, refusal, onConfirm, onCancel }: SuspensionDialogProps) {
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

  const refused = refusalKey(refusal);
  const action = t(suspending ? "users.suspend" : "users.lift");

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
          {t(suspending ? "users.suspendTitle" : "users.liftTitle", { email })}
        </h2>
        <p className="text-xs text-ink-2">{t(suspending ? "users.suspendBody" : "users.liftBody")}</p>

        {refused !== null && (
          <p role="alert" className="text-sm text-loss">
            {t(refused)}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={cancel}
            disabled={pending}
            className="min-h-11 rounded-md border border-rule px-3 text-sm text-ink-2 hover:bg-panel-2 disabled:opacity-50"
          >
            {t("users.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className="inline-flex min-h-11 items-center rounded-md bg-loss px-3 text-sm font-medium text-ink hover:opacity-90 disabled:opacity-50"
          >
            {pending ? t("users.working") : action}
          </button>
        </div>
      </div>
    </dialog>
  );
}
