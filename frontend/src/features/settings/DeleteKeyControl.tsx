import { useEffect, useRef, useState } from "react";
import { Trash } from "lucide-react";
import { useTranslation } from "react-i18next";

import { DeleteKeyDialog } from "@/features/settings/DeleteKeyDialog";
import { useDeleteCredential } from "@/shared/api/credentials";

export interface DeleteKeyControlProps {
  exchange: string;
  /** The exchange's proper name. */
  name: string;
  /** The last four characters of the key the list says is stored, or none: then there is no button. */
  last4: string | null;
  /** The card's form is open, or a save is in flight: the button is disabled. */
  disabled?: boolean;
  /** The dialog was opened: the page ends the notice of an earlier save. */
  onOpen?: () => void;
  /** A delete worked: the page says so and moves the focus to the card's `Add key`. */
  onDeleted?: () => void;
  /** The dialog closed and the card has no `Delete key` to take the focus back: the page picks it up. */
  onFocusFallback?: () => void;
  /**
   * The dialog closed without a delete that worked, and the focus has been placed. The page keeps a card with no key
   * in the document while its dialog is open (decision 80); from here it may let it go.
   */
  onClosed?: () => void;
}

/**
 * The `Delete key` button of a card whose list says a key is stored, and the confirmation it opens. The button is
 * always enabled when shown (the panel does not guess what the server will allow) except while the card's form is
 * open. One click only opens the dialog: the `DELETE` goes from the dialog's own button, and while it is in flight
 * a second press sends nothing more.
 *
 * The control stays in the document when the card has no key, so a dialog that is open survives the list being
 * read again behind it: a delete whose answer was lost says so on screen even if the card already shows no key.
 * The list is read again by the mutation itself (`useDeleteCredential`), not by this component.
 */
export function DeleteKeyControl({
  exchange,
  name,
  last4,
  disabled = false,
  onOpen,
  onDeleted,
  onFocusFallback,
  onClosed,
}: DeleteKeyControlProps) {
  const { t } = useTranslation();
  const remove = useDeleteCredential();
  /** The dialog is open for the key ending in these characters, kept from the moment it opened. */
  const [shown, setShown] = useState<{ last4: string } | null>(null);
  /** Counts the closings that owe the focus to somebody: a new number asks again. */
  const [refocus, setRefocus] = useState(0);
  const button = useRef<HTMLButtonElement>(null);
  /** Marks the request in flight before the next render can disable the button. */
  const inFlight = useRef(false);

  // The focus returns once the dialog has left the document: a modal dialog makes the page behind it inert.
  useEffect(() => {
    if (refocus === 0) return;
    if (button.current !== null) button.current.focus();
    else onFocusFallback?.();
    onClosed?.();
    // Only a new closing asks for the focus, not a new callback.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refocus]);

  const open = () => {
    if (last4 === null) return;
    remove.reset();
    setShown({ last4 });
    onOpen?.();
  };

  const close = () => {
    if (inFlight.current) return;
    remove.reset();
    setShown(null);
    setRefocus((count) => count + 1);
  };

  const confirm = () => {
    if (inFlight.current) return;
    inFlight.current = true;
    remove.mutate(exchange, {
      onSuccess: (result) => {
        if (result.kind !== "deleted") return;
        setShown(null);
        onDeleted?.();
      },
      onSettled: () => {
        inFlight.current = false;
      },
    });
  };

  return (
    <>
      {last4 !== null && (
        <button
          ref={button}
          type="button"
          aria-label={`${t("settings.card.delete")} ${name}`}
          disabled={disabled}
          onClick={open}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-md border border-loss px-3.5 text-sm text-loss hover:bg-panel-2 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain"
        >
          <Trash aria-hidden="true" className="size-4 shrink-0" />
          {t("settings.card.delete")}
        </button>
      )}
      {shown !== null && (
        <DeleteKeyDialog
          name={name}
          last4={shown.last4}
          pending={remove.isPending}
          result={remove.data ?? null}
          onConfirm={confirm}
          onCancel={close}
        />
      )}
    </>
  );
}
