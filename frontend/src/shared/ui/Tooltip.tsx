import type { LucideIcon } from "lucide-react";
import { type MouseEvent, useEffect, useId, useRef, useState } from "react";
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
  /** Where the tip opens: above its trigger, or below it (lined up with its right edge, or with its left edge for
   * `below-start`), for a trigger at the top of the page or of a table that scrolls sideways. */
  placement?: "above" | "below" | "below-start";
  /** Shown also while this is true: the pointer is on what the tip is about, outside the trigger (a figure's value). */
  open?: boolean;
}

/** What inside a trigger acts on a click by itself: a click there is the control's, never the tip's. */
const CONTROLS = "button, a, input, select, textarea, label, [role='button']";

/**
 * A short explanation shown on hover and on keyboard focus, hidden on leave, blur and Escape. The trigger is
 * focusable itself, so a keyboard user reaches it; while the tip is shown the trigger is described by it.
 *
 * Every tip behaves as the information button does (L63, L64): a click or a tap on the trigger pins the tip
 * open (on a phone, the only way to open it) until a click on the trigger again, a press outside or Escape.
 * The tip takes the pointer, and a bridge over the gap to its trigger keeps the pointer inside on the way, so
 * a long tip can be read.
 */
export function Tooltip({
  text,
  children,
  describes = true,
  tabbable = true,
  className = "inline-flex",
  placement = "above",
  open = false,
}: TooltipProps) {
  const id = useId();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [pinned, setPinned] = useState(false);
  const wrapper = useRef<HTMLSpanElement | null>(null);
  const shown = (pinned || hovered || focused || open) && !dismissed;

  // A press outside the trigger and its tip lets a pinned tip go.
  useEffect(() => {
    if (!pinned) return;
    const releaseOutside = (event: globalThis.MouseEvent) => {
      if (event.target instanceof Node && wrapper.current?.contains(event.target)) return;
      setPinned(false);
      setHovered(false);
    };
    document.addEventListener("mousedown", releaseOutside);
    return () => document.removeEventListener("mousedown", releaseOutside);
  }, [pinned]);

  const pin = (event: MouseEvent<HTMLSpanElement>) => {
    // Around a control, the click is the control's action; the tip still shows on its hover and focus.
    if (!tabbable) return;
    const control = event.target instanceof Element ? event.target.closest(CONTROLS) : null;
    if (control !== null && event.currentTarget.contains(control)) return;
    if (pinned) {
      setPinned(false);
      setDismissed(true);
    } else {
      setPinned(true);
      setDismissed(false);
    }
  };

  return (
    <span
      ref={wrapper}
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
      onClick={pin}
      onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        setPinned(false);
        setDismissed(true);
      }}
    >
      {children}
      {shown && (
        <span
          id={id}
          role="tooltip"
          // The tip resets what a trigger's cell would hand it (one line, a monospaced face), so it wraps in its own box (L18).
          // The bridge (`before:`) spans the 4 px gap, so the pointer moving onto the tip never leaves the trigger.
          className={`absolute z-10 before:absolute before:inset-x-0 before:h-1 w-max max-w-64 whitespace-normal break-words rounded-md border border-rule bg-panel-2 px-2 py-1 text-left font-sans text-xs font-normal normal-case tracking-normal text-ink motion-safe:animate-tip-in ${
            placement === "above"
              ? "bottom-full left-0 mb-1 before:-bottom-1"
              : placement === "below"
                ? "right-0 top-full mt-1 before:-top-1"
                : "left-0 top-full mt-1 before:-top-1"
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
  /** Shown also while the pointer is on the value the icon names. */
  open?: boolean;
}

/**
 * An icon in place of a label: it keeps the label as its accessible name and explains itself in a tooltip. It is
 * drawn lighter and a little larger (18 px) than the info button's grey 16 px "i", so the two are never confused.
 */
export function IconTip({ icon: Icon, label, open = false }: IconTipProps) {
  return (
    // The tip repeats the name, so it does not also describe the trigger: a screen reader would read it twice.
    <Tooltip text={label} describes={false} open={open}>
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
    // A click pins the tip, so the (i) shows the hand, as the information button does (decision 61, L65).
    <Tooltip text={text} placement={placement} className="inline-flex cursor-pointer">
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
