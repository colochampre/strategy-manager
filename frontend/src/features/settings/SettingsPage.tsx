import { useTranslation } from "react-i18next";

import { DeleteAccountSection } from "@/features/settings/DeleteAccountSection";
import { DisplayNameSection } from "@/features/settings/DisplayNameSection";
import { IdentitySection } from "@/features/settings/IdentitySection";
import { PageHeader } from "@/shared/ui/PageHeader";

/**
 * Mi cuenta (S4): the person's data, the legal acceptance and the deletion of the account. The exchange keys
 * live in Link exchange (`features/exchanges`), apart from the name and the details of the user.
 *
 * The page has no width cap of its own: like Strategies it fills the shell's column (decision 60).
 */
export function SettingsPage() {
  const { t } = useTranslation();

  return (
    // The sections stack 4 apart, as every view's blocks do; the title alone steps 6 to them (L.13).
    <div className="flex flex-col gap-4">
      <PageHeader
        crumbs={[{ label: t("settings.title") }]}
        title={t("settings.title")}
        subtitle={t("pageHeader.account")}
      />
      <DisplayNameSection />
      <IdentitySection />
      <DeleteAccountSection />
    </div>
  );
}
