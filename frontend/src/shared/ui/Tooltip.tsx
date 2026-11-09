import type { LucideIcon } from "lucide-react";
import { useId, useState } from "react";
import type { ReactNode } from "react";

interface TooltipProps {
  /** What the tip says. */
  text: string;
  children: ReactNode;
  /** Whether the tip describes the trigger. Off where the tip only repeats the trigger's own name. */
  describes?: boolean;
  /** Whether the tip's own wrapper takes keyboard focus. Off around a control that takes it itself: focus on the
   * control still shows the tip, and the keyboard meets one stop, not two. */
  tabbable?: boolean;
  /** How the wrapper lays out in its row; it is an inline flex box unless told otherwise (for example `flex w-full`). */
  className?: string;
  /** Where the tip opens: above its trigger, or below and aligned to its right edge, for a trigger at the top of the page. */
  placement?: "above" | "below";
}

/**
 * A short explanation shown on hover and on keyboard focus, hidden on leave, blur and Escape. The trigger is
 * focusable itself, so a keyboard user reaches it; while the tip is shown the trigger is described by it.
 */
export function Tooltip({
  text,
  children,
  describes = true,
  tabbable = true,
  className = "inline-flex",
  placement = "above",
}: TooltipProps) {
  const id = useId();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const shown = (hovered || focused) && !dismissed;

  return (
    <span
      tabIndex={tabbable ? 0 : undefined}
      aria-describedby={shown && describes ? id : undefined}
      className={`relative ${className}`}
      onMouseEnter={() => {
        setHovered(true);
        setDismissed(false);
      }}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => {
        setFocused(true);
        setDismissed(false);
      }}
      onBlur={() => setFocused(false)}
      onKeyDown={(event) => {
        if (event.key === "Escape") setDismissed(true);
      }}
    >
      {children}
      {shown && (
        <span
          id={id}
          role="tooltip"
          className={`pointer-events-none absolute z-10 w-max max-w-64 rounded-md border border-rule bg-panel-2 px-2 py-1 text-xs font-normal normal-case tracking-normal text-ink ${
            placement === "above" ? "bottom-full left-0 mb-1" : "right-0 top-full mt-1"
          }`}
        >
          {text}
        </span>
      )}
    </span>
  );
}

interface IconTipProps {
  icon: LucideIcon;
  /** Both the icon's accessible name and the tip: what the text it replaces used to say. */
  label: string;
}

/**
 * An icon in place of a label: it keeps the label as its accessible name and explains itself in a tooltip. It is
 * drawn lighter and a little larger (18 px) than the info button's grey 16 px "i", so the two are never confused.
 */
export function IconTip({ icon: Icon, label }: IconTipProps) {
  return (
    // The tip repeats the name, so it does not also describe the trigger: a screen reader would read it twice.
    <Tooltip text={label} describes={false}>
      <span role="img" aria-label={label} className="inline-flex text-ink-2">
        <Icon aria-hidden="true" className="size-4.5" />
      </span>
    </Tooltip>
  );
}

interface InfoTipProps {
  /** The (i)'s accessible name: what it explains. */
  label: string;
  /** The explanation, shown on hover and focus. */
  text: string;
  placement?: "above" | "below";
}

/**
 * An "i" in a circle that explains on hover and focus, for a place with no room to open a text beneath it, such as
 * the top bar. The 16 px grey glyph of the info button, so the two read as the same sign.
 */
export function InfoTip({ label, text, placement = "above" }: InfoTipProps) {
  return (
    <Tooltip text={text} placement={placement}>
      <span role="img" aria-label={label} className="inline-flex size-6 items-center justify-center text-ink-3 hover:text-ink-2">
        <svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="8" cy="8" r="6.75" />
          <circle cx="8" cy="5" r="0.75" fill="currentColor" stroke="none" />
          <path d="M8 7.25v4.5" strokeLinecap="round" />
        </svg>
      </span>
    </Tooltip>
  );
}
