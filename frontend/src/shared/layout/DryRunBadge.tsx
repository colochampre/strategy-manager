import { useTranslation } from "react-i18next";

import { useHealth } from "@/shared/api/health";
import { cn } from "@/shared/lib/cn";

const NEUTRAL = "border-rule text-ink-3";

/**
 * Reads the server's own `dry_run` through `GET /health`. Every state that is
 * not a confirmed answer stays neutral, so a failed or pending read can never
 * be mistaken for either mode, and never for "live":
 *
 * - `dry_run: true`  -> "Dry run", amber (one of the four "needs your decision" places).
 * - `dry_run: false` -> "Live", in the loss colour, because real money moves.
 * - loading          -> "Checking mode", neutral.
 * - error            -> "Mode unknown", neutral.
 */
export function DryRunBadge() {
  const { t } = useTranslation();
  const health = useHealth();

  let label: string;
  let tone: string;
  if (health.isError) {
    label = t("status.unknown");
    tone = NEUTRAL;
  } else if (health.data === undefined) {
    label = t("status.checking");
    tone = NEUTRAL;
  } else if (health.data.dryRun) {
    label = t("status.dryRun");
    tone = "border-decision text-decision";
  } else {
    label = t("status.live");
    tone = "border-loss text-loss";
  }

  return (
    <span
      role="status"
      className={cn("rounded-sm border px-2 py-1 font-mono text-xs uppercase tracking-widest", tone)}
    >
      {label}
    </span>
  );
}
