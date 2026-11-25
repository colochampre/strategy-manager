import { useTranslation } from "react-i18next";

import { AccountDetails } from "@/features/settings/AccountDetails";
import { DeleteAccountSection } from "@/features/settings/DeleteAccountSection";
import { LanguageSection } from "@/features/settings/LanguageSection";
import { ModeSection } from "@/features/settings/ModeSection";
import { PageHeader } from "@/shared/ui/PageHeader";

/**
 * Mi cuenta (S4, ex7): the person's data, the mode, the language and the deletion of the account. The exchange keys
 * live in Link exchange (`features/exchanges`), apart from the name and the details of the user. The mode is changed
 * here and only shown in the top row (S7, rewritten by L12).
 *
 * The page has no width cap of its own: like Strategies it fills the shell's column (decision 60).
 */
export function SettingsPage() {
  const { t } = useTranslation();

  return (
    // The cards stack 4 apart, as every view's blocks do; the title alone steps 6 to them (L.13).
    <div className="flex flex-col gap-4">
      <PageHeader
        crumbs={[{ label: t("settings.title") }]}
        title={t("settings.title")}
        subtitle={t("pageHeader.account")}
      />
      <AccountDetails />
      <ModeSection />
      <LanguageSection />
      <DeleteAccountSection />
    </div>
  );
}
