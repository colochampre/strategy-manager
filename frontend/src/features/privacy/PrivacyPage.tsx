import { useTranslation } from "react-i18next";

/**
 * The privacy policy (Ley 25.326), served inside the panel: everyone who reaches
 * it has signed in, and the notice in the shell links it on their first visit.
 *
 * Every line is a key under `privacy.sections`, in this order. Bracketed
 * placeholders ([FULL NAME], [ADDRESS], retention) are the owner's to fill
 * before the panel moves (openspec/changes/public-site/tasks.md).
 */
const SECTIONS: ReadonlyArray<{ id: string; paragraphs?: string[]; items?: string[]; after?: string[] }> = [
  { id: "who", paragraphs: ["body"] },
  { id: "stores", paragraphs: ["intro"], items: ["email", "name", "keys", "balances", "strategies", "trades"], after: ["never"] },
  { id: "use", paragraphs: ["body"] },
  { id: "public", paragraphs: ["body", "subscribers", "private", "admin"] },
  { id: "others", items: ["cloudflare", "exchanges", "tradingview", "server"], after: ["abroad"] },
  { id: "retention", items: ["account", "trades", "logs", "backups"] },
  { id: "rights", paragraphs: ["body", "deletion", "authority"] },
  { id: "security", paragraphs: ["body"] },
  { id: "changes", paragraphs: ["body"] },
];

export function PrivacyPage() {
  const { t } = useTranslation();
  const key = (section: string, line: string) => t(`privacy.sections.${section}.${line}`);

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <h1 className="mb-2 font-display text-2xl font-bold text-ink">{t("privacy.title")}</h1>
      <p className="text-sm text-ink-3">{t("privacy.updated")}</p>
      <p className="text-sm leading-relaxed text-ink-2">{t("privacy.intro")}</p>
      {SECTIONS.map(({ id, paragraphs = [], items = [], after = [] }) => (
        <section key={id} aria-labelledby={`privacy-${id}`} className="flex flex-col gap-2">
          <h2 id={`privacy-${id}`} className="font-display text-base font-semibold text-ink">
            {key(id, "title")}
          </h2>
          {paragraphs.map((line) => (
            <p key={line} className="text-sm leading-relaxed text-ink-2">
              {key(id, line)}
            </p>
          ))}
          {items.length > 0 && (
            <ul className="flex list-disc flex-col gap-1 pl-5 text-sm leading-relaxed text-ink-2">
              {items.map((line) => (
                <li key={line}>{key(id, line)}</li>
              ))}
            </ul>
          )}
          {after.map((line) => (
            <p key={line} className="text-sm leading-relaxed text-ink-2">
              {key(id, line)}
            </p>
          ))}
        </section>
      ))}
    </div>
  );
}
