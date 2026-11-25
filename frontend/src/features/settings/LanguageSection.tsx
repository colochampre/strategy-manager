import { useTranslation } from "react-i18next";

import { CARD_ROW, Card } from "@/shared/ui/Card";
import { Flag } from "@/shared/layout/Flag";
import { Segmented } from "@/shared/ui/Segmented";

type Language = "es" | "en";

/**
 * The language of the panel (ex7, "Idioma"): the same switch the flag in the top row makes, as the prototype draws
 * it, with each language in its own name and its flag. The choice is i18next's own, so it is kept the way the flag
 * keeps it.
 */
export function LanguageSection() {
  const { t, i18n } = useTranslation();
  const current: Language = i18n.resolvedLanguage === "es" ? "es" : "en";

  return (
    <Card title={t("settings.language.title")}>
      <div className={CARD_ROW}>
        <p className="max-w-[60ch] text-[15px] text-ink">{t("settings.language.description")}</p>
        <Segmented
          label={t("settings.language.group")}
          value={current}
          onChange={(language) => void i18n.changeLanguage(language)}
          options={[
            { value: "es", label: "Español", icon: <Flag country="ar" /> },
            { value: "en", label: "English", icon: <Flag country="us" /> },
          ]}
        />
      </div>
    </Card>
  );
}
