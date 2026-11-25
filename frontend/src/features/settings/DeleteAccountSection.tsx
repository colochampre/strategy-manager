import { Trash } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DeleteAccountDialog } from "@/features/settings/DeleteAccountDialog";
import { useDeleteAccount, useMe } from "@/shared/api/me";
import { Card } from "@/shared/ui/Card";
import { DANGER_CONTROL } from "@/shared/ui/danger-control";

/**
 * The last card of Mi cuenta (account-deletion S1; ex7's "Eliminar cuenta", loss-coloured): what deleting the account
 * erases, closes and keeps, and the button that opens the confirmation. The deletion itself is `useDeleteAccount`'s;
 * once it worked the app draws only the screen that says so.
 */
export function DeleteAccountSection() {
  const { t } = useTranslation();
  const me = useMe().data;
  const deletion = useDeleteAccount();
  const [open, setOpen] = useState(false);

  if (me === undefined) return null;

  const close = () => {
    setOpen(false);
    deletion.reset();
  };

  return (
    <>
      <Card title={t("settings.account.title")} danger>
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
          <div className="flex min-w-0 flex-col gap-3">
            <ul className="flex flex-col gap-1.5 text-[15px] text-ink">
              <li>{t("settings.account.erased")}</li>
              <li>{t("settings.account.closed")}</li>
              <li>{t("settings.account.kept")}</li>
            </ul>
            <p className="text-[13px] text-ink-3">{t("settings.account.refused")}</p>
          </div>
          {/* Deleting is final, so the button keeps its words beside its icon, as a strategy's delete does. */}
          <button type="button" className={DANGER_CONTROL} onClick={() => setOpen(true)}>
            <Trash aria-hidden="true" className="size-4" />
            {t("settings.account.open")}
          </button>
        </div>
      </Card>
      {open && (
        <DeleteAccountDialog
          email={me.email}
          pending={deletion.isPending}
          result={deletion.data ?? null}
          onConfirm={() => deletion.mutate()}
          onCancel={close}
        />
      )}
    </>
  );
}
