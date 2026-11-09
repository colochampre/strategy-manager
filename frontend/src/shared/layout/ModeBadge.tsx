import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { useTranslation } from "react-i18next";

import { type ChangeModeResult, type Mode, useChangeMode, useMe } from "@/shared/api/me";
import { cn } from "@/shared/lib/cn";
import { InfoTip } from "@/shared/ui/Tooltip";
import { ModeDialog } from "@/shared/layout/ModeDialog";

const PILL = "rounded-sm border px-2 py-1 font-mono text-xs uppercase tracking-widest";
const NEUTRAL = "border-rule text-ink-3";
const AMBER = "border-decision text-decision";

const MODES: readonly Mode[] = ["LIVE", "SIMULATION"];

interface ModeMenuProps {
  current: Mode;
  /** Called with the mode picked when it is not the one in force; that one only closes the menu. */
  onPick: (mode: Mode) => void;
}

/**
 * The badge as a drop-down (owner, 2026-11-06): its chevron opens the two modes, the one in force checked.
 * Picking the other one hands it to the confirmation; nothing changes from the menu itself. It closes on a pick,
 * on Escape (the focus back on the badge), on a second click of the badge and on a press anywhere outside it.
 */
function ModeMenu({ current, onPick }: ModeMenuProps) {
  const { t } = useTranslation();
  const menuId = useId();
  const [expanded, setExpanded] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const live = current === "LIVE";
  const label = live ? t("status.live") : t("status.simulation");
  const nameOf = (mode: Mode) => (mode === "LIVE" ? t("status.live") : t("status.simulation"));

  useEffect(() => {
    if (!expanded) return undefined;
    itemRefs.current[MODES.indexOf(current)]?.focus();
    const closeOutside = (event: PointerEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) setExpanded(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [expanded, current]);

  const pick = (mode: Mode) => {
    setExpanded(false);
    if (mode !== current) onPick(mode);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      setExpanded(false);
      buttonRef.current?.focus();
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const focused = itemRefs.current.findIndex((item) => item === document.activeElement);
    const step = event.key === "ArrowDown" ? 1 : -1;
    itemRefs.current[(focused + step + MODES.length) % MODES.length]?.focus();
  };

  return (
    <div ref={wrapperRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-label={t("mode.change", { mode: label })}
        aria-haspopup="menu"
        aria-expanded={expanded}
        aria-controls={expanded ? menuId : undefined}
        onClick={() => setExpanded((open) => !open)}
        className="inline-flex min-h-11 items-center rounded-sm hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain"
      >
        <span className={cn(PILL, "inline-flex items-center gap-1", live ? "border-gain text-gain" : AMBER)}>
          {label}
          <ChevronDown aria-hidden="true" className="size-3 shrink-0" />
        </span>
      </button>
      {expanded && (
        <div
          id={menuId}
          role="menu"
          aria-label={t("mode.menu")}
          onKeyDown={handleKeyDown}
          className="absolute right-0 top-full z-20 mt-1 flex min-w-40 flex-col rounded-md border border-rule bg-panel p-1"
        >
          {MODES.map((mode, index) => (
            <button
              key={mode}
              ref={(node) => {
                itemRefs.current[index] = node;
              }}
              type="button"
              role="menuitemradio"
              aria-checked={mode === current}
              onClick={() => pick(mode)}
              className={cn(
                "flex min-h-11 items-center justify-between gap-3 rounded-sm px-3 font-mono text-xs uppercase tracking-widest hover:bg-panel-2 focus-visible:bg-panel-2 focus-visible:outline-none",
                mode === "LIVE" ? "text-gain" : "text-decision",
              )}
            >
              {nameOf(mode)}
              {mode === current && <Check aria-hidden="true" className="size-3.5 shrink-0" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * The signed-in user's mode, from `GET /api/me` (multi-user design AD7). Every state that is not a confirmed
 * answer stays neutral and cannot be clicked, so a failed or pending read can never be mistaken for either mode,
 * and never for "live":
 *
 * - the brake on     -> "Simulation forced", amber, not a button: the brake forces it for everyone, whatever the
 *   user's own mode says, and neither direction can be asked for.
 * - `SIMULATION`     -> "Simulation", amber (one of the "needs your decision" places), a drop-down.
 * - `LIVE`           -> "Live", in the gain colour: the badge and the open-position marks share the colour of
 *   "live", and the badge states the mode, it is not an alarm. Red is kept for what is wrong. A drop-down.
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
        // Why the badge is forced waits behind an (i) right of it, opening below: the bar is at the top of the page.
        <span className="inline-flex items-center gap-1">
          <span role="status" className={cn(PILL, AMBER)}>
            {t("status.forced")}
          </span>
          <InfoTip label={t("mode.brakeLabel")} text={t("mode.brakeInfo")} placement="below" />
        </span>
      );
    }
    return <ModeMenu current={me.data.mode} onPick={open} />;
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
