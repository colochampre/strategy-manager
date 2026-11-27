import { type KeyboardEvent, type SyntheticEvent, useId, useLayoutEffect, useRef, useState } from "react";
import { OctagonX } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/shared/api/client";
import { type OpenPosition, useCloseNow } from "@/shared/api/positions";
import { tableFigureText } from "@/shared/lib/figure-text";

/** The text of a refused close: the status decides, never the server's wording. */
function refusalText(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) return "positions.closeNow.errors.gone";
  return "positions.closeNow.errors.generic";
}

interface CloseNowDialogProps {
  pair: string;
  size: string;
  pending: boolean;
  /** The mutation's error, if any. */
  error: unknown;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Confirms a close at market, which cannot be undone: it names the pair and the size first, and confirm is its own
 * button, so the click that opened the dialog sends nothing. A native `<dialog>`, with Escape and the browser's
 * `cancel` event routed to one handler, as `LeaveDialog` does.
 */
function CloseNowDialog({ pair, size, pending, error, onConfirm, onCancel }: CloseNowDialogProps) {
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
      className="fixed inset-0 m-auto w-[calc(100%-2rem)] max-w-lg rounded-lg whitespace-normal break-words text-left border border-rule bg-panel p-0 text-ink backdrop:bg-ground/80 motion-safe:animate-dialog-in"
    >
      <div className="flex flex-col gap-4 p-6 font-sans">
        <h2 id={titleId} className="text-sm font-semibold text-ink">
          {t("positions.closeNow.confirmTitle", { pair })}
        </h2>
        <p className="text-xs text-ink-2">{t("positions.closeNow.confirmBody", { pair, size })}</p>

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
            className="min-h-11 rounded-lg border border-rule px-3 text-sm text-ink-2 hover:bg-panel-2 disabled:opacity-50"
          >
            {t("positions.closeNow.cancel")}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-lg bg-loss px-3 text-sm font-medium text-ink hover:opacity-90 disabled:opacity-50"
          >
            <OctagonX aria-hidden="true" className="size-4 shrink-0" />
            {pending ? t("positions.closeNow.pending") : t("positions.closeNow.confirm")}
          </button>
        </div>
      </div>
    </dialog>
  );
}

/** The dialog and the request, mounted only while the dialog is open: a mutation exists only once someone asks. */
function CloseNowFlow({ position, size, onDone }: { position: OpenPosition; size: string; onDone: () => void }) {
  const close = useCloseNow();
  return (
    <CloseNowDialog
      pair={position.markets.join(" / ")}
      size={size}
      pending={close.isPending}
      error={close.error}
      onConfirm={() => close.mutate(position.allocation_id, { onSuccess: onDone })}
      onCancel={onDone}
    />
  );
}

/**
 * "Close now" on one open position, an icon with its name and a tooltip as the panel's other actions. A position
 * whose size or side could not be read has none: it names nothing to confirm. It sends nothing itself, it only
 * opens the dialog.
 */
export function CloseNowControl({ position, appearance = "icon" }: { position: OpenPosition; appearance?: "icon" | "text" }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  if (position.size === null || position.side === null) return null;
  const size = `${tableFigureText(position.size) ?? position.size}${position.base_currency === null ? "" : ` ${position.base_currency}`}`;
  const label = t("positions.closeNow.label");

  return (
    <>
      {appearance === "text" ? (
        // ex1's small outlined danger button: the same flow, drawn as words.
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex h-[30px] items-center rounded-lg border border-loss/55 px-[11px] font-sans text-[13px] font-medium text-loss hover:bg-loss/10"
        >
          {label}
        </button>
      ) : (
        <button
          type="button"
          aria-label={label}
          title={label}
          onClick={() => setOpen(true)}
          className="ml-2 inline-flex size-8 items-center justify-center rounded-lg border border-rule align-middle text-ink-2 hover:bg-panel-2 hover:text-loss"
        >
          <OctagonX aria-hidden="true" className="size-4 shrink-0" />
        </button>
      )}
      {open && <CloseNowFlow position={position} size={size} onDone={() => setOpen(false)} />}
    </>
  );
}
