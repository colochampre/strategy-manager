import { useEffect, useId } from "react";
import { useTranslation } from "react-i18next";

import type { DeleteResult } from "@/shared/api/credentials";

export interface DeleteKeyDialogProps {
  /** The exchange's proper name. */
  name: string;
  /** The last four characters of the stored key. */
  last4: string;
  /** The delete is in flight. */
  pending: boolean;
  /** How the last attempt ended, or none yet. */
  result: DeleteResult | null;
  onConfirm: () => void;
  onCancel: () => void;
}

/** STUB (task 13.6.1): sends the delete on the click that opened it and shows nothing for any answer. */
export function DeleteKeyDialog({ name, onConfirm }: DeleteKeyDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  useEffect(() => {
    onConfirm();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <dialog open aria-labelledby={titleId}>
      <h2 id={titleId}>{t("settings.card.delete")}</h2>
      <p>{name}</p>
    </dialog>
  );
}
