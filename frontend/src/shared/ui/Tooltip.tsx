import type { LucideIcon } from "lucide-react";
import { useId, useState } from "react";
import type { ReactNode } from "react";

interface TooltipProps {
  /** What the tip says. */
  text: string;
  children: ReactNode;
  /** Whether the tip describes the trigger. Off where the tip only repeats the trigger's own name. */
  describes?: boolean;
}

/**
 * A short explanation shown on hover and on keyboard focus, hidden on leave, blur and Escape. The trigger is
 * focusable itself, so a keyboard user reaches it; while the tip is shown the trigger is described by it.
 */
export function Tooltip({ text, children, describes = true }: TooltipProps) {
  const id = useId();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const shown = (hovered || focused) && !dismissed;

  return (
    <span
      tabIndex={0}
      aria-describedby={shown && describes ? id : undefined}
      className="relative inline-flex"
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
          className="pointer-events-none absolute bottom-full left-0 z-10 mb-1 w-max max-w-64 rounded-md border border-rule bg-panel-2 px-2 py-1 text-xs font-normal normal-case tracking-normal text-ink"
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
