import { type KeyboardEvent, type SyntheticEvent, useId, useLayoutEffect, useRef, useState } from "react";
import { Trash } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { DeleteAccountResult } from "@/shared/api/me";

export interface DeleteAccountDialogProps {
  /** The signed-in e-mail: typing it is the confirmation (account-deletion S1). */
  email: string;
  /** The deletion is in flight: nothing can close the dialog and both buttons are off. */
  pending: boolean;
  /** How the last attempt ended, or none yet. */
  result: DeleteAccountResult | null;
  onConfirm: () => void;
  onCancel: () => void;
}

const BUTTON =
  "min-h-11 rounded-md px-3.5 text-sm disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain";

const FIELD =
  "min-h-11 w-full rounded-md border border-rule bg-ground px-3 text-sm text-ink focus-visible:outline-2 focus-visible:outline-gain";

/** The e-mail as it is stored is normal: lower case, no spaces. What is typed is read the same way. */
function sameEmail(typed: string, email: string): boolean {
  return typed.trim().toLowerCase() === email.trim().toLowerCase();
}

/**
 * Confirms the deletion of the account. Unlike a key's delete, there is something to type: the e-mail, as GitHub
 * asks for a repository's name, because nothing of the account can be brought back. Nothing is sent on the click
 * that opened it, `Cancel` has the focus, and the request goes only from this dialog's own button.
 *
 * A native `<dialog>` upgraded to a modal where the browser supports it, with Escape and the browser's `cancel`
 * event routed to one handler that does nothing while the request is in flight, as `DeleteKeyDialog` does. Every
 * outcome's text is chosen here, never the server's wording.
 */
export function DeleteAccountDialog({ email, pending, result, onConfirm, onCancel }: DeleteAccountDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const fieldId = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const [typed, setTyped] = useState("");

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null) return undefined;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
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
      case "holds": {
        const lines: string[] = [];
        if (result.symbols.length > 0) {
          lines.push(t("settings.account.heldSymbols", { symbols: result.symbols.join(", ") }));
        }
        for (const strategy of result.strategies) {
          lines.push(
            strategy.symbols.length > 0
              ? t("settings.account.heldStrategy", { name: strategy.name, symbols: strategy.symbols.join(", ") })
              : t("settings.account.heldStrategyUnlisted", { name: strategy.name }),
          );
        }
        return { text: t("settings.account.holds"), lines };
      }
      case "changed":
        return { text: t("settings.account.changed"), lines: [] as string[] };
      case "unknown":
        return { text: t("settings.account.failed"), lines: [] as string[] };
      default:
        // Nothing yet, a deletion that worked (the app is leaving) or a 401 (the page is loaded again to sign in).
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
          {t("settings.account.confirmTitle")}
        </h2>
        <p className="text-xs text-ink-2">{t("settings.account.confirmBody")}</p>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={fieldId} className="text-[13px] text-ink-2">
            {t("settings.account.emailLabel")}
          </label>
          <input
            id={fieldId}
            type="email"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            autoComplete="off"
            disabled={pending}
            className={FIELD}
          />
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
            {t("settings.account.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending || !sameEmail(typed, email)}
            className={`${BUTTON} inline-flex items-center gap-1.5 bg-loss font-medium text-ink hover:opacity-90`}
          >
            <Trash aria-hidden="true" className="size-4 shrink-0" />
            {pending ? t("settings.account.pending") : t("settings.account.confirm")}
          </button>
        </div>
      </div>
    </dialog>
  );
}
