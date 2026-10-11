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
}

/** STUB (task 13.6.1): a button that opens the dialog. */
export function DeleteKeyControl({ exchange, name, last4 }: DeleteKeyControlProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const remove = useDeleteCredential();
  if (last4 === null) return null;
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
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
