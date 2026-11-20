import { LEGAL_CONTACT, LegalDocument, type LegalSection } from "@/shared/legal/LegalDocument";

/** Where every request about this policy goes. */
export const PRIVACY_CONTACT = LEGAL_CONTACT;

/**
 * The privacy policy (Ley 25.326), served inside the panel: everyone who reaches
 * it has signed in, and the sign-up form links it before anyone accepts it.
 * Every line is a key under `privacy.sections`, in this order.
 */
const SECTIONS: ReadonlyArray<LegalSection> = [
  { id: "who", paragraphs: ["body"] },
  {
    id: "stores",
    paragraphs: ["intro"],
    items: ["email", "identity", "name", "keys", "balances", "strategies", "trades", "acceptances", "logs", "messages"],
    after: ["never"],
  },
  { id: "use", paragraphs: ["body", "identity", "required", "basis"] },
  { id: "public", paragraphs: ["body", "subscribers", "private", "admin"] },
  {
    id: "others",
    items: ["cloudflare", "exchanges", "tradingview", "server", "authorities"],
    after: ["abroad", "links"],
  },
  { id: "cookies", paragraphs: ["access", "storage", "none"] },
  { id: "retention", items: ["account", "identity", "trades", "acceptances", "logs", "backups"] },
  { id: "rights", paragraphs: ["body", "deletion", "authority"] },
  { id: "security", paragraphs: ["body", "limits"] },
  { id: "age", paragraphs: ["body"] },
  { id: "changes", paragraphs: ["body"] },
  { id: "contact", paragraphs: ["body"] },
];

export function PrivacyPage() {
  return <LegalDocument ns="privacy" sections={SECTIONS} />;
}
