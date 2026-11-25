import { useTranslation } from "react-i18next";

import { useMe } from "@/shared/api/me";
import { cn } from "@/shared/lib/cn";
import { InfoTip } from "@/shared/ui/Tooltip";

/**
 * The prototype's `.badge-live`: 36 px tall like the icon buttons beside it, a 1 px tinted border, a tinted
 * background, a dot and the word in sentence case (L12: "En vivo", not "EN VIVO").
 */
const BADGE = "inline-flex h-9 items-center gap-2 rounded-lg border px-3.5 text-sm font-medium";

type Tone = "live" | "neutral" | "unknown" | "amber";

const TONE: Record<Tone, { badge: string; dot: string }> = {
  unknown: { badge: "border-rule bg-panel text-ink-3", dot: "bg-ink-3" },
  live: { badge: "border-gain/45 bg-gain/12 text-gain-bright", dot: "bg-gain ring-[3px] ring-gain/25" },
  neutral: { badge: "border-ink-3/40 bg-ink-3/10 text-ink-2", dot: "bg-ink-3 ring-[3px] ring-ink-3/25" },
  amber: { badge: "border-decision/45 bg-decision/12 text-decision", dot: "bg-decision ring-[3px] ring-decision/25" },
};

function Badge({ tone, children }: { tone: Tone; children: string }) {
  return (
    <span role="status" className={cn(BADGE, TONE[tone].badge)}>
      <i data-dot="true" aria-hidden="true" className={cn("size-[7px] shrink-0 rounded-full", TONE[tone].dot)} />
      {children}
    </span>
  );
}

/**
 * The signed-in user's mode, from `GET /api/me` (multi-user design AD7), only shown (L12): the switch is in Mi
 * cuenta, where `ModeSection` keeps every rule of the change. Every state that is not a confirmed answer stays
 * neutral, so a failed or pending read can never be mistaken for either mode, and never for "live":
 *
 * - the brake on     -> "Simulation forced", amber: the brake forces it for everyone, whatever the user's own mode
 *   says. It is the one state that is the owner's to act on, so it keeps the "needs your decision" colour.
 * - `LIVE`           -> "Live", in the gain colour: the badge states the mode, it is not an alarm.
 * - `SIMULATION`     -> "Simulation", neutral.
 * - loading          -> "Checking mode", neutral.
 * - error            -> "Mode unknown", neutral.
 */
export function ModeBadge() {
  const { t } = useTranslation();
  const me = useMe();

  if (me.isError) return <Badge tone="unknown">{t("status.unknown")}</Badge>;
  if (me.data === undefined) return <Badge tone="unknown">{t("status.checking")}</Badge>;
  if (me.data.dryRunBrake) {
    return (
      // Why the badge is forced waits behind an (i) right of it, opening below: the bar is at the top of the page.
      <span className="inline-flex items-center gap-1">
        <Badge tone="amber">{t("status.forced")}</Badge>
        <InfoTip label={t("mode.brakeLabel")} text={t("mode.brakeInfo")} placement="below" />
      </span>
    );
  }
  return me.data.mode === "LIVE" ? (
    <Badge tone="live">{t("status.live")}</Badge>
  ) : (
    <Badge tone="neutral">{t("status.simulation")}</Badge>
  );
}
