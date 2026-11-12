import { useTranslation } from "react-i18next";

/**
 * The privacy policy (Ley 25.326), served inside the panel: everyone who reaches
 * it has signed in, and the notice in the shell links it on their first visit.
 *
 * Every line is a key under `privacy.sections`, in this order. The name and
 * address of the person responsible come from the build
 * (`VITE_PRIVACY_OWNER_NAME`, `VITE_PRIVACY_OWNER_ADDRESS`, set in the untracked
 * `frontend/.env.production.local`), never from this public repository; without
 * them the page shows its placeholders. The other bracketed placeholders
 * (server, retention) are the owner's to fill before the panel moves
 * (openspec/changes/public-site/tasks.md).
 */

/** Where every request about this policy goes (Cloudflare Email Routing forwards it to the owner). */
export const PRIVACY_CONTACT = "privacy@strategymanager.trade";

const SECTIONS: ReadonlyArray<{ id: string; paragraphs?: string[]; items?: string[]; after?: string[] }> = [
  { id: "who", paragraphs: ["body"] },
  {
    id: "stores",
    paragraphs: ["intro"],
    items: ["email", "name", "keys", "balances", "strategies", "trades", "logs", "messages"],
    after: ["never"],
  },
  { id: "use", paragraphs: ["body", "basis"] },
  { id: "public", paragraphs: ["body", "subscribers", "private", "admin"] },
  { id: "others", items: ["cloudflare", "exchanges", "tradingview", "server"], after: ["abroad", "links"] },
  { id: "cookies", paragraphs: ["access", "storage", "none"] },
  { id: "retention", items: ["account", "trades", "logs", "backups"] },
  { id: "rights", paragraphs: ["body", "deletion", "authority"] },
  { id: "security", paragraphs: ["body", "limits"] },
  { id: "age", paragraphs: ["body"] },
  { id: "changes", paragraphs: ["body"] },
  { id: "contact", paragraphs: ["body"] },
];

const TEXT = "text-sm leading-relaxed text-ink-2";

export function PrivacyPage() {
  const { t } = useTranslation();
  const values = {
    name: import.meta.env.VITE_PRIVACY_OWNER_NAME || t("privacy.placeholder.name"),
    address: import.meta.env.VITE_PRIVACY_OWNER_ADDRESS || t("privacy.placeholder.address"),
    contact: PRIVACY_CONTACT,
  };
  const key = (section: string, line: string) => t(`privacy.sections.${section}.${line}`, values);

  return (
    <article className="mx-auto flex w-full max-w-3xl flex-col gap-4 sm:text-justify">
      <header className="flex flex-col">
        <h1 className="mb-2 text-center font-display text-2xl font-bold text-ink">{t("privacy.title")}</h1>
        <p className="text-center text-sm text-ink-3">{t("privacy.updated")}</p>
      </header>
      <p className={TEXT}>{t("privacy.intro")}</p>
      {SECTIONS.map(({ id, paragraphs = [], items = [], after = [] }) => (
        <section key={id} aria-labelledby={`privacy-${id}`} className="flex flex-col gap-2">
          <h2
            id={`privacy-${id}`}
            className="font-display text-sm font-semibold tracking-wide text-ink uppercase"
          >
            {key(id, "title")}
          </h2>
          {paragraphs.map((line) => (
            <p key={line} className={TEXT}>
              {key(id, line)}
            </p>
          ))}
          {items.length > 0 && (
            <ul className={`flex list-disc flex-col gap-1 pl-5 ${TEXT}`}>
              {items.map((line) => (
                <li key={line}>{key(id, line)}</li>
              ))}
            </ul>
          )}
          {after.map((line) => (
            <p key={line} className={TEXT}>
              {key(id, line)}
            </p>
          ))}
        </section>
      ))}
    </article>
  );
}
