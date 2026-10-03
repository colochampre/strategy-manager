import { type FormEvent, type KeyboardEvent, type SyntheticEvent, useId, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/shared/api/client";

interface DeleteStrategyDialogProps {
  name: string;
  pending: boolean;
  /** The mutation's error, if any: an `ApiError` with a refusal code, or anything else. */
  error: unknown;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * The six counts `HAS_HISTORY` carries, in the order the server lists them, with
 * the i18n key of the line each one gets. Enablement events have no line: since
 * migration 0028 they are deleted with the strategy and block nothing, so naming
 * them beside a signal would suggest something the owner has to resolve. The
 * count is still validated with the rest before any line is trusted.
 */
const HISTORY_KINDS = [
  ["signals", "signals"],
  ["reservations", "reservations"],
  ["execution_attempts", "executionAttempts"],
  ["ledger_entries", "ledgerEntries"],
  ["booking_proposals", "bookingProposals"],
  ["enablement_events", null],
] as const;

interface HistoryLine {
  key: string;
  count: number;
}

/**
 * The non-zero blocking kinds of a refusal's `history`. A body that is missing, is not
 * an object or carries any count that is not a non-negative integer yields no
 * lines at all: the main sentence is then shown alone, never a half-trusted list.
 */
function historyLines(error: ApiError): HistoryLine[] {
  const history = error.fields?.history;
  if (typeof history !== "object" || history === null) return [];
  const counts = history as Record<string, unknown>;
  const lines: HistoryLine[] = [];
  for (const [field, key] of HISTORY_KINDS) {
    const count = counts[field];
    if (typeof count !== "number" || !Number.isInteger(count) || count < 0) return [];
    if (key !== null && count > 0) lines.push({ key, count });
  }
  return lines;
}

/**
 * Confirms an irreversible delete. The owner must type the strategy's name; the
 * destructive button stays disabled until the text matches exactly, and Enter
 * in the field submits only then. Cancel and Escape send nothing. A refusal
 * from the server is rendered inside, with the counts that block it.
 *
 * A native `<dialog>` upgraded to a modal where the browser supports it. Escape
 * is handled on the key, and the browser's own `cancel` event is routed to the
 * same handler, so neither path can close the dialog behind the component's back.
 */
export function DeleteStrategyDialog({ name, pending, error, onConfirm, onCancel }: DeleteStrategyDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const fieldId = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [typed, setTyped] = useState("");
  const matches = typed === name;

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

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (matches && !pending) onConfirm();
  };

  const refusal = (() => {
    if (error === null || error === undefined) return null;
    if (error instanceof ApiError && error.code === "STILL_ENABLED") {
      return { text: t("strategies.delete.errors.stillEnabled"), lines: [] as HistoryLine[] };
    }
    if (error instanceof ApiError && error.code === "HAS_HISTORY") {
      return { text: t("strategies.delete.errors.hasHistory"), lines: historyLines(error) };
    }
    return { text: t("strategies.delete.errors.generic"), lines: [] as HistoryLine[] };
  })();

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      onKeyDown={handleKeyDown}
      onCancel={handleCancelEvent}
      className="fixed inset-0 m-auto w-full max-w-lg rounded-lg border border-rule bg-panel p-0 text-ink backdrop:bg-ground/80"
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-4 p-6">
        <h2 id={titleId} className="text-sm font-semibold text-ink">
          {t("strategies.delete.confirmTitle", { name })}
        </h2>
        <p className="text-xs text-ink-2">{t("strategies.delete.confirmBody", { name })}</p>

        <div className="flex flex-col gap-1">
          <label htmlFor={fieldId} className="text-xs text-ink-3">
            {t("strategies.delete.typeName")}
          </label>
          <input
            id={fieldId}
            type="text"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            disabled={pending}
            autoComplete="off"
            className="rounded-md border border-rule bg-panel-2 px-3 py-2 text-sm text-ink focus:border-gain focus:outline-none disabled:opacity-50"
          />
        </div>

        {refusal !== null && (
          <div role="alert" className="flex flex-col gap-1 text-sm text-loss">
            <p>{refusal.text}</p>
            {refusal.lines.length > 0 && (
              <ul className="list-disc pl-5 text-xs">
                {refusal.lines.map((line) => (
                  <li key={line.key}>{t(`strategies.delete.history.${line.key}`, { count: line.count })}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={cancel}
            disabled={pending}
            className="rounded-md border border-rule px-3 py-1.5 text-sm text-ink-2 hover:bg-panel-2 disabled:opacity-50"
          >
            {t("strategies.delete.cancel")}
          </button>
          <button
            type="submit"
            disabled={!matches || pending}
            className="rounded-md bg-loss px-3 py-1.5 text-sm font-medium text-ink hover:opacity-90 disabled:opacity-50"
          >
            {pending ? t("strategies.delete.pending") : t("strategies.delete.confirm")}
          </button>
        </div>
      </form>
    </dialog>
  );
}
