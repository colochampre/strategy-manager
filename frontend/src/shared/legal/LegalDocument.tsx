import { useTranslation } from "react-i18next";
import { Link } from "react-router";

/** Where every request about the privacy policy or the terms goes (Cloudflare Email Routing forwards it to the owner). */
export const LEGAL_CONTACT = "privacy@strategymanager.trade";

/** One section of a legal document: keys under `<ns>.sections.<id>`, drawn in this order. */
export interface LegalSection {
  id: string;
  paragraphs?: string[];
  items?: string[];
  after?: string[];
  /** A link drawn last, labelled by a full i18n key. */
  link?: { to: string; label: string };
}

const TEXT = "text-sm leading-relaxed text-ink-2";

/**
 * A legal document of the panel (the privacy policy, the terms of service):
 * a centred title and date, an intro, then its sections, justified from `sm` up.
 *
 * The name and address of the person responsible come from the build
 * (`VITE_PRIVACY_OWNER_NAME`, `VITE_PRIVACY_OWNER_ADDRESS`, set in the untracked
 * `frontend/.env.production.local`), never from this public repository; without
 * them the document shows `legal.placeholder`. Other bracketed placeholders are
 * the owner's to fill before the panel moves (openspec/changes/public-site/tasks.md).
 */
export function LegalDocument({ ns, sections }: { ns: "privacy" | "terms"; sections: ReadonlyArray<LegalSection> }) {
  const { t } = useTranslation();
  const values = {
    name: import.meta.env.VITE_PRIVACY_OWNER_NAME || t("legal.placeholder.name"),
    address: import.meta.env.VITE_PRIVACY_OWNER_ADDRESS || t("legal.placeholder.address"),
    contact: LEGAL_CONTACT,
  };
  const key = (section: string, line: string) => t(`${ns}.sections.${section}.${line}`, values);

  return (
    <article className="mx-auto flex w-full max-w-3xl flex-col gap-4 sm:text-justify">
      <header className="flex flex-col">
        <h1 className="mb-2 text-center font-display text-2xl font-bold text-ink">{t(`${ns}.title`)}</h1>
        <p className="text-center text-sm text-ink-3">{t(`${ns}.updated`)}</p>
      </header>
      <p className={TEXT}>{t(`${ns}.intro`)}</p>
      {sections.map(({ id, paragraphs = [], items = [], after = [], link }) => (
        <section key={id} aria-labelledby={`${ns}-${id}`} className="flex flex-col gap-2">
          <h2 id={`${ns}-${id}`} className="font-display text-sm font-semibold tracking-wide text-ink uppercase">
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
          {link && (
            <p className={TEXT}>
              <Link to={link.to} className="text-gain hover:text-gain-bright">
                {t(link.label)}
              </Link>
            </p>
          )}
        </section>
      ))}
    </article>
  );
}
