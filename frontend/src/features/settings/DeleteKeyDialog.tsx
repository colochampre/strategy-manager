import { type KeyboardEvent, type SyntheticEvent, useId, useLayoutEffect, useRef } from "react";
import { Trash } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { DeleteResult, NotFlatLists } from "@/shared/api/credentials";

export interface DeleteKeyDialogProps {
  /** The exchange's proper name. */
  name: string;
  /** The last four characters of the stored key, and nothing more of it. */
  last4: string;
  /** The delete is in flight: nothing can close the dialog and both buttons are off. */
  pending: boolean;
  /** How the last attempt ended, or none yet. */
  result: DeleteResult | null;
  onConfirm: () => void;
  onCancel: () => void;
}

const BUTTON =
  "min-h-11 rounded-md px-3.5 text-sm disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain";

/** One line per kind that has entries, in the order the server lists them; a kind with none has no line. */
function reasonLines(lists: NotFlatLists, t: (key: string, options: Record<string, unknown>) => string): string[] {
  const lines: string[] = [];
  if (lists.enabledStrategies.length > 0) {
    lines.push(
      t("settings.delete.reasons.enabledStrategies", {
        count: lists.enabledStrategies.length,
        names: lists.enabledStrategies.join(", "),
      }),
    );
  }
  if (lists.symbols.length > 0) {
    lines.push(t("settings.delete.reasons.symbols", { symbols: lists.symbols.join(", ") }));
  }
  if (lists.allocations > 0) lines.push(t("settings.delete.reasons.allocations", { count: lists.allocations }));
  if (lists.liveReservations > 0) {
    lines.push(t("settings.delete.reasons.liveReservations", { count: lists.liveReservations }));
  }
  if (lists.inFlightAttempts > 0) {
    lines.push(t("settings.delete.reasons.inFlightAttempts", { count: lists.inFlightAttempts }));
  }
  return lines;
}

/**
 * Confirms the delete of an exchange's key. The confirmation is a plain button: there is nothing to type, so the
 * safeguards are that nothing is sent on the click that opened the dialog, that `Cancel` has the focus when it
 * opens, and that the request goes only from this dialog's own `Delete key`.
 *
 * A native `<dialog>` upgraded to a modal where the browser supports it, with Escape and the browser's own
 * `cancel` event routed to one handler that does nothing while the request is in flight, as `ArchiveDialog` does.
 *
 * The text of every outcome is chosen here from what the panel read, never from the server's wording.
 */
export function DeleteKeyDialog({ name, last4, pending, result, onConfirm, onCancel }: DeleteKeyDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null) return undefined;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    // The safe button has the focus: the browser would pick the first focusable, jsdom picks nothing.
    cancelRef.current?.focus();
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

  const outcome = (() => {
    switch (result?.kind) {
      case "notFlat":
        return result.lists === null
          ? { text: t("settings.delete.errors.notFlatUnlisted", { exchange: name }), lines: [] as string[] }
          : {
              text: t("settings.delete.errors.notFlat", { exchange: name }),
              lines: reasonLines(result.lists, (key, options) => t(key, options)),
            };
      case "gone":
        return { text: t("settings.delete.errors.gone", { exchange: name }), lines: [] as string[] };
      case "unknown":
        return { text: t("settings.delete.errors.unknown"), lines: [] as string[] };
      default:
        // Nothing yet, a delete that worked (the dialog is closing) or a 401 (the token gate takes the page).
        return null;
    }
  })();

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
          {t("settings.delete.confirmTitle", { exchange: name })}
        </h2>
        <div className="flex flex-col gap-2 text-xs text-ink-2">
          <p>{t("settings.delete.confirmBody", { last4, exchange: name })}</p>
          <p>{t("settings.delete.condition", { exchange: name })}</p>
        </div>

        {outcome !== null && (
          <div role="alert" className="flex flex-col gap-1 text-sm text-loss">
            <p>{outcome.text}</p>
            {outcome.lines.length > 0 && (
              <ul className="list-disc pl-5 text-xs">
                {outcome.lines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={cancel}
            disabled={pending}
            className={`${BUTTON} border border-rule text-ink-2 hover:bg-panel-2`}
          >
            {t("settings.delete.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className={`${BUTTON} inline-flex items-center gap-1.5 bg-loss font-medium text-ink hover:opacity-90`}
          >
            <Trash aria-hidden="true" className="size-4 shrink-0" />
            {pending ? t("settings.delete.pending") : t("settings.delete.confirm")}
          </button>
        </div>
      </div>
    </dialog>
  );
}
