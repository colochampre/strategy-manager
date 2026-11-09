import type { LucideIcon } from "lucide-react";

import { Tooltip } from "@/shared/ui/Tooltip";

interface ColumnHeadProps {
  icon: LucideIcon;
  /** The column's name: the icon's accessible name, and the start of its tooltip. */
  label: string;
  /** What the column's figures mean, where a note used to say it below the table; told after the name. */
  hint?: string | undefined;
  /** Which edge of the column the tip lines up with: a left-aligned column's start, a figure column's end. */
  align?: "start" | "end";
}

/**
 * A table's column name as an icon, the panel's figure icons in a header: the name stays the header's accessible
 * name, and the tooltip says it, then the column's note when it has one. The tip opens below, since a header sits
 * at the top of a table that may scroll sideways and would cut a tip opened above.
 */
export function ColumnHead({ icon: Icon, label, hint, align = "end" }: ColumnHeadProps) {
  return (
    <Tooltip
      text={hint === undefined ? label : `${label}. ${hint}`}
      describes={hint !== undefined}
      placement={align === "start" ? "below-start" : "below"}
    >
      <span role="img" aria-label={label} className="inline-flex text-ink-2">
        <Icon aria-hidden="true" className="size-4" />
      </span>
    </Tooltip>
  );
}
