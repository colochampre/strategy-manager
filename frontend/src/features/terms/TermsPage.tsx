import { LegalDocument, type LegalSection } from "@/shared/legal/LegalDocument";

/**
 * The terms of service, served inside the panel beside the privacy policy and
 * laid out like it. Every line is a key under `terms.sections`, in this order.
 * A draft until the owner's lawyer reviews it (openspec/changes/public-site).
 */
const SECTIONS: ReadonlyArray<LegalSection> = [
  { id: "who", paragraphs: ["body"] },
  { id: "service", paragraphs: ["body", "custody", "modes", "how"] },
  { id: "eligibility", paragraphs: ["body", "data", "false"] },
  {
    id: "commitments",
    paragraphs: ["intro"],
    items: ["signals", "stop", "keys", "records", "changes"],
    after: ["notGuaranteed"],
  },
  { id: "obligations", paragraphs: ["intro"], items: ["data", "email", "keys", "settings", "law"] },
  { id: "advice", paragraphs: ["body"] },
  { id: "risks", paragraphs: ["intro"], items: ["loss", "past", "signals", "exchange", "strategies"] },
  { id: "thirdParty", paragraphs: ["body", "losses", "control"] },
  { id: "authors", paragraphs: ["body", "subscribers", "removal"] },
  { id: "use", paragraphs: ["intro"], items: ["attack", "illegal", "laundering", "others"] },
  { id: "availability", paragraphs: ["body"] },
  { id: "liability", paragraphs: ["body", "market", "tradingview", "exchange", "rights"] },
  { id: "records", paragraphs: ["body", "authorities"] },
  { id: "price", paragraphs: ["body"] },
  { id: "stopping", paragraphs: ["you", "us", "positions"] },
  { id: "privacy", paragraphs: ["body"], link: { to: "/privacy", label: "privacy.read" } },
  { id: "changes", paragraphs: ["body"] },
  { id: "law", paragraphs: ["body"] },
  { id: "contact", paragraphs: ["body"] },
];

export function TermsPage() {
  return <LegalDocument ns="terms" sections={SECTIONS} />;
}
