import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";

import { type ChangeModeResult, type Mode, useChangeMode, useMe } from "@/shared/api/me";
import { cn } from "@/shared/lib/cn";
import { ModeDialog } from "@/shared/layout/ModeDialog";

const PILL = "rounded-sm border px-2 py-1 font-mono text-xs uppercase tracking-widest";
const NEUTRAL = "border-rule text-ink-3";
const AMBER = "border-decision text-decision";

/**
 * The signed-in user's mode, from `GET /api/me` (multi-user design AD7). Every state that is not a confirmed
 * answer stays neutral and cannot be clicked, so a failed or pending read can never be mistaken for either mode,
 * and never for "live":
 *
 * - the brake on     -> "Simulation forced", amber, not a button: the brake forces it for everyone, whatever the
 *   user's own mode says, and neither direction can be asked for.
 * - `SIMULATION`     -> "Simulation", amber (one of the "needs your decision" places), a button.
 * - `LIVE`           -> "Live", in the gain colour: the badge and the open-position marks share the colour of
 *   "live", and the badge states the mode, it is not an alarm. Red is kept for what is wrong. A button.
 * - loading          -> "Checking mode", neutral.
 * - error            -> "Mode unknown", neutral.
 *
 * The dialog stands apart from the badge, so a refusal stays on screen when the read it triggered changes the
 * badge under it: the brake pulled a moment ago turns the button into the forced badge.
 */
export function ModeBadge() {
  const { t } = useTranslation();
  const me = useMe();
  const change = useChangeMode();
  const [target, setTarget] = useState<Mode | null>(null);
  const [result, setResult] = useState<ChangeModeResult | null>(null);

  const open = (mode: Mode) => {
    setResult(null);
    setTarget(mode);
  };

  const confirm = () => {
    if (target === null) return;
    change.mutate(target, {
      onSuccess: (outcome) => {
        if (outcome.kind === "changed") setTarget(null);
        else setResult(outcome);
      },
    });
  };

  const badge = () => {
    if (me.isError) {
      return (
        <span role="status" className={cn(PILL, NEUTRAL)}>
          {t("status.unknown")}
        </span>
      );
    }
    if (me.data === undefined) {
      return (
        <span role="status" className={cn(PILL, NEUTRAL)}>
          {t("status.checking")}
        </span>
      );
    }
    if (me.data.dryRunBrake) {
      return (
        <span role="status" title={t("mode.forcedHint")} className={cn(PILL, AMBER)}>
          {t("status.forced")}
        </span>
      );
    }
    const live = me.data.mode === "LIVE";
    const label = live ? t("status.live") : t("status.simulation");
    return (
      <button
        type="button"
        aria-label={t("mode.change", { mode: label })}
        onClick={() => open(live ? "SIMULATION" : "LIVE")}
        className="inline-flex min-h-11 items-center rounded-sm hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain"
      >
        <span className={cn(PILL, "inline-flex items-center gap-1", live ? "border-gain text-gain" : AMBER)}>
          {label}
          <ChevronDown aria-hidden="true" className="size-3 shrink-0" />
        </span>
      </button>
    );
  };

  return (
    <>
      {badge()}
      {target !== null && (
        <ModeDialog
          target={target}
          pending={change.isPending}
          result={result}
          onConfirm={confirm}
          onCancel={() => setTarget(null)}
        />
      )}
    </>
  );
}
