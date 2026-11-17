import type { LucideIcon } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

import { cn } from "@/shared/lib/cn";
import { IconTip } from "@/shared/ui/Tooltip";

interface FigureProps {
  label: string;
  testId: string;
  value: string;
  tone?: string | undefined;
  info?: ReactNode;
  /** Drawn in place of the label, which then names it and explains it on hover. */
  icon?: LucideIcon;
  /** Added to the value's classes, last, for a lead figure that is larger or must not break. */
  valueClassName?: string;
  /** The icon left of the value instead of above it: for a lead figure, whose larger value the icon would not line up over. */
  inline?: boolean;
  /** Drawn right of the value, inside it: an information button about the figure. */
  after?: ReactNode;
  /** Added to the figure's own classes: where it is drawn, by the width it has. */
  className?: string | undefined;
}

/** One figure: its label, or its icon, centred over its value. */
export function Figure({
  label,
  testId,
  value,
  tone = "text-ink",
  info,
  icon,
  valueClassName,
  inline = false,
  after,
  className,
}: FigureProps) {
  // The icon's tooltip also answers the pointer on the value it names (owner, 2026-11-17).
  const [onValue, setOnValue] = useState(false);
  return (
    // The label takes the room left, so a label that wraps never lowers its figure below the others in the row.
    <div
      className={cn(
        "flex w-fit",
        inline ? "flex-row items-center gap-2" : "flex-col items-center justify-between gap-0.5",
        className,
      )}
    >
      {/* Lifted above a card's stretched link, so the icon still answers the pointer with its tooltip. */}
      <dt className="relative z-10 flex items-start text-xs text-ink-3">
        {icon === undefined ? label : <IconTip icon={icon} label={label} open={onValue} />}
        {info}
      </dt>
      <dd
        data-testid={testId}
        onMouseEnter={() => setOnValue(true)}
        onMouseLeave={() => setOnValue(false)}
        className={cn(
          "font-mono text-sm lg:whitespace-nowrap",
          after !== undefined && "inline-flex items-center",
          tone,
          valueClassName,
        )}
      >
        {value}
        {after}
      </dd>
    </div>
  );
}
