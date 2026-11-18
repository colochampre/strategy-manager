import { Trash } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { DeleteAccountDialog } from "@/features/settings/DeleteAccountDialog";
import { useDeleteAccount, useMe } from "@/shared/api/me";
import { DANGER_CONTROL } from "@/shared/ui/danger-control";
import { ReportSection } from "@/shared/ui/ReportSection";

/**
 * The last section of Settings (account-deletion S1): what deleting the account erases, closes and keeps, and the
 * button that opens the confirmation. The deletion itself is `useDeleteAccount`'s; once it worked the app draws
 * only the screen that says so.
 */
export function DeleteAccountSection() {
  const { t } = useTranslation();
  const me = useMe().data;
  const deletion = useDeleteAccount();
  const [open, setOpen] = useState(false);
  const headingId = useId();

  if (me === undefined) return null;

  const close = () => {
    setOpen(false);
    deletion.reset();
  };

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <h2 id={headingId} className="font-display text-base font-semibold text-ink">
        {t("settings.account.title")}
      </h2>
      <ReportSection>
        <div className="flex flex-col gap-3">
          <ul className="flex flex-col gap-1.5 text-xs text-ink-2">
            <li>{t("settings.account.erased")}</li>
            <li>{t("settings.account.closed")}</li>
            <li>{t("settings.account.kept")}</li>
          </ul>
          <p className="text-xs text-ink-3">{t("settings.account.refused")}</p>
          {/* Deleting is final, so the button keeps its words beside its icon, as a strategy's delete does. */}
          <button type="button" className={`${DANGER_CONTROL} self-start`} onClick={() => setOpen(true)}>
            <Trash aria-hidden="true" className="size-4" />
            {t("settings.account.open")}
          </button>
        </div>
      </ReportSection>
      {open && (
        <DeleteAccountDialog
          email={me.email}
          pending={deletion.isPending}
          result={deletion.data ?? null}
          onConfirm={() => deletion.mutate()}
          onCancel={close}
        />
      )}
    </section>
  );
}
