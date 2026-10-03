import { type KeyboardEvent, type SyntheticEvent, useId, useLayoutEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/shared/api/client";

interface ArchiveDialogProps {
  name: string;
  pending: boolean;
  /** The mutation's error, if any: an `ApiError` with a refusal code, or anything else. */
  error: unknown;
  onConfirm: () => void;
  onCancel: () => void;
}

interface Reason {
  key: string;
  values: Record<string, string | number>;
}

function isStrings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

/**
 * What an `OPEN_POSITION` refusal says still holds the strategy: the symbols it
 * holds, and how many allocations, live reservations and in-flight attempts it
 * has (the ids themselves tell the owner nothing). A body in which any of the
 * four is missing or is not a list of strings yields no lines at all: the main
 * sentence is then shown alone, never a half-trusted list.
 */
function openPositionReasons(error: ApiError): Reason[] {
  const { symbols, allocations, live_reservations: reservations, in_flight_attempts: attempts } = error.fields ?? {};
  if (!isStrings(symbols) || !isStrings(allocations) || !isStrings(reservations) || !isStrings(attempts)) return [];
  const reasons: Reason[] = [];
  if (symbols.length > 0) reasons.push({ key: "symbols", values: { symbols: symbols.join(", ") } });
  if (allocations.length > 0) reasons.push({ key: "allocations", values: { count: allocations.length } });
  if (reservations.length > 0) reasons.push({ key: "liveReservations", values: { count: reservations.length } });
  if (attempts.length > 0) reasons.push({ key: "inFlightAttempts", values: { count: attempts.length } });
  return reasons;
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
      className="fixed inset-0 m-auto w-full max-w-lg rounded-lg border border-rule bg-panel p-0 text-ink backdrop:bg-ground/80"
    >
      <div className="flex flex-col gap-4 p-6">
        <h2 id={titleId} className="text-sm font-semibold text-ink">
          {t("strategies.archive.confirmTitle", { name })}
        </h2>
        <p className="text-xs text-ink-2">{t("strategies.archive.confirmBody", { name })}</p>

        {refusal !== null && (
          <div role="alert" className="flex flex-col gap-1 text-sm text-loss">
            <p>{refusal.text}</p>
            {refusal.reasons.length > 0 && (
              <ul className="list-disc pl-5 text-xs">
                {refusal.reasons.map((reason) => (
                  <li key={reason.key}>{t(`strategies.archive.reasons.${reason.key}`, reason.values)}</li>
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
            {t("strategies.archive.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className="rounded-md bg-loss px-3 py-1.5 text-sm font-medium text-ink hover:opacity-90 disabled:opacity-50"
          >
            {pending ? t("strategies.archive.pending") : t("strategies.archive.confirm")}
          </button>
        </div>
      </div>
    </dialog>
  );
}
