import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DeleteKeyDialog } from "@/features/settings/DeleteKeyDialog";
import { useDeleteCredential } from "@/shared/api/credentials";

export interface DeleteKeyControlProps {
  exchange: string;
  /** The exchange's proper name. */
  name: string;
  /** The last four characters of the key the list says is stored, or none. */
  last4: string | null;
  /** The card's form is open, or a save is in flight: the button is disabled. */
  disabled?: boolean;
  /** The dialog was opened: the page ends the notice of an earlier save. */
  onOpen?: () => void;
  /** A delete worked: the page says so and moves the focus to the card's `Add key`. */
  onDeleted?: () => void;
  /** The dialog closed and the card has no `Delete key` to take the focus back: the page picks it up. */
  onFocusFallback?: () => void;
}

/** STUB (task 13.6.1): a button that opens the dialog. */
export function DeleteKeyControl({ exchange, name, last4 }: DeleteKeyControlProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const remove = useDeleteCredential();
  if (last4 === null) return null;
  return (
    <>
      <button type="button" aria-label={`${t("settings.card.delete")} ${name}`} onClick={() => setOpen(true)}>
        {t("settings.card.delete")}
      </button>
      {open && (
        <DeleteKeyDialog
          name={name}
          last4={last4}
          pending={remove.isPending}
          result={remove.data ?? null}
          onConfirm={() => remove.mutate(exchange)}
          onCancel={() => setOpen(false)}
        />
      )}
    </>
  );
}
