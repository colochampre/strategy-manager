import { useTranslation } from "react-i18next";

import { ORIGIN_STYLE } from "@/features/positions/origin";
import type { Origin } from "@/features/positions/origin";

interface OriginTagProps {
  origin: Origin;
}

/** The origin's word in its own token. The table is `origin.ts`; this file writes no colour of its own. */
export function OriginTag({ origin }: OriginTagProps) {
  const { t } = useTranslation();
  const entry = ORIGIN_STYLE[origin];
  return <span className={entry.text}>{t(entry.textKey)}</span>;
}
