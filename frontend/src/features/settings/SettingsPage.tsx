import { useTranslation } from "react-i18next";

import { ExchangeKeyCard } from "@/features/settings/ExchangeKeyCard";
import served from "@/shared/credentials/served-exchanges.json";

/** STUB (RED): the title and one card per served exchange, read from nothing. */
export function SettingsPage() {
  const { t } = useTranslation();

  return (
    <div>
      <h1 className="font-display text-2xl font-bold text-ink">{t("settings.title")}</h1>
      {Object.keys(served).map((exchange) => (
        <ExchangeKeyCard key={exchange} exchange={exchange} entry={undefined} poolOn={null} served />
      ))}
    </div>
  );
}
