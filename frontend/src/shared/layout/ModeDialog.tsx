import { type KeyboardEvent, type SyntheticEvent, useId, useLayoutEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import type { ChangeModeResult, Mode } from "@/shared/api/me";

export interface ModeDialogProps {
  /** The mode the user would move to. */
  target: Mode;
  /** The change is in flight: nothing can close the dialog and both buttons are off. */
  pending: boolean;
  /** How the last attempt ended, or none yet. */
  result: ChangeModeResult | null;
  onConfirm: () => void;
  onCancel: () => void;
}

const BUTTON =
  "min-h-11 rounded-md px-3.5 text-sm disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain";

/**
 * Confirms a change of the user's own mode. The safeguards are `DeleteKeyDialog`'s: nothing is sent on the click
 * that opened the dialog, `Cancel` has the focus when it opens, and the request goes only from this dialog's own
 * button. Moving to live says that real orders will be placed.
 *
 * The text of every outcome is chosen here from what the panel read, never from the server's wording.
 */
export function ModeDialog({ target, pending, result, onConfirm, onCancel }: ModeDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const texts = target === "LIVE" ? "mode.toLive" : "mode.toSimulation";

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
      case "brakeOn":
        return { text: t("mode.errors.brakeOn"), symbols: [] as string[] };
      case "needsKey":
        return { text: t("mode.errors.needsKey"), symbols: [] as string[] };
      case "notFlat":
        return { text: t("mode.errors.notFlat"), symbols: result.symbols };
      case "unknown":
        return { text: t("mode.errors.unknown"), symbols: [] as string[] };
      default:
        // Nothing yet, a change that worked (the dialog is closing) or a 401 (the page is loaded again to sign in).
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
          {t(`${texts}.title`)}
        </h2>
        <div className="flex flex-col gap-2 text-xs text-ink-2">
          <p>{t(`${texts}.body`)}</p>
          <p>{t(`${texts}.note`)}</p>
        </div>

        {outcome !== null && (
          <div role="alert" className="flex flex-col gap-1 text-sm text-loss">
            <p>{outcome.text}</p>
            {outcome.symbols.length > 0 && (
              <ul className="list-disc pl-5 font-mono text-xs">
                {outcome.symbols.map((symbol) => (
                  <li key={symbol}>{symbol}</li>
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
            {t("mode.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className={`${BUTTON} bg-gain font-medium text-ground hover:opacity-90`}
          >
            {pending ? t("mode.pending") : t(`${texts}.confirm`)}
          </button>
        </div>
      </div>
    </dialog>
  );
}
