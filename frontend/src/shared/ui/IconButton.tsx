import type { LucideIcon } from "lucide-react";
import type { Ref } from "react";

import { cn } from "@/shared/lib/cn";
import { Tooltip } from "@/shared/ui/Tooltip";

export type IconButtonTone = "neutral" | "primary" | "danger";

interface IconButtonProps {
  /** The button's accessible name and its tooltip: what the text it replaces used to say. */
  label: string;
  icon: LucideIcon;
  onClick?: (() => void) | undefined;
  /** The button submits its form instead of being a plain button. */
  submit?: boolean;
  disabled?: boolean | undefined;
  tone?: IconButtonTone;
  /** Spins the icon, for a request in flight. */
  spin?: boolean;
  /** The accessible name when it says more than the tip (a delete that names its target); the label otherwise. */
  name?: string | undefined;
  /** The id of a text that explains the button (why it is unavailable). */
  describedBy?: string | undefined;
  /**
   * `sm` is the 32 px button of a table row's actions (ex6 `.acts .icon-btn`): it carries its label as a `title`
   * instead of a floating tip, which a table that scrolls sideways would clip.
   */
  size?: "md" | "sm";
  ref?: Ref<HTMLButtonElement>;
}

const TONE: Record<IconButtonTone, string> = {
  neutral: "border-rule text-ink-2 hover:bg-panel-2",
  primary: "border-gain bg-gain text-ground hover:opacity-90",
  danger: "border-loss text-loss hover:bg-loss/10",
};

/**
 * A button that is only an icon: its label is its accessible name and its tooltip, so a screen reader hears what
 * the text said. A square of 44 px, like the copy icon of the sharing block. The tip only repeats the name, so it
 * does not also describe the button, and the button takes focus itself (one keyboard stop).
 */
export function IconButton({
  label,
  icon: Icon,
  onClick,
  submit = false,
  disabled,
  tone = "neutral",
  spin = false,
  name,
  describedBy,
  size = "md",
  ref,
}: IconButtonProps) {
  const small = size === "sm";
  const button = (
    <button
      type={submit ? "submit" : "button"}
      ref={ref}
      aria-label={name ?? label}
      aria-describedby={describedBy}
      title={small ? label : undefined}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-lg border disabled:opacity-50",
        small ? "size-8" : "size-11",
        TONE[tone],
      )}
    >
      <Icon aria-hidden="true" className={cn("size-4", spin && "animate-spin")} />
    </button>
  );
  if (small) return button;
  return (
    <Tooltip text={label} describes={false} tabbable={false}>
      {button}
    </Tooltip>
  );
}
