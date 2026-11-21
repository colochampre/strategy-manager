import { useTranslation } from "react-i18next";

import { LEGAL_CONTACT } from "@/shared/legal/LegalDocument";

/**
 * What a suspended account sees in place of the panel (public-site LS9): that it can no longer open or subscribe,
 * that what it holds still closes, and where to write.
 */
export function SuspendedNotice() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-4">
      <h1 className="font-display text-xl font-bold text-ink">{t("suspension.title")}</h1>
      <p className="text-sm text-ink-2">{t("suspension.body", { contact: LEGAL_CONTACT })}</p>
    </div>
  );
}
