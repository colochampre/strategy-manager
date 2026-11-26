import { Tooltip } from "@/shared/ui/Tooltip";

interface HintedHeadProps {
  /** The column's name, written in words (L30). */
  label: string;
  /** What the column's figures mean, where a note used to say it below the table. */
  hint?: string | undefined;
  /** Which edge of the column the note lines up with: a left-aligned column's start, a figure column's end. */
  align?: "start" | "end";
}

/**
 * A table's column name in words, as the prototype's tables write it (L30). A column with a note underlines its
 * name with dots, and the note opens below on hover and on focus: a header sits at the top of a table that may
 * scroll sideways, and would cut a note opened above.
 */
export function HintedHead({ label, hint, align = "end" }: HintedHeadProps) {
  if (hint === undefined) return <>{label}</>;
  return (
    <Tooltip text={hint} describes placement={align === "start" ? "below-start" : "below"}>
      <span className="underline decoration-ink-3 decoration-dotted underline-offset-[3px]">{label}</span>
    </Tooltip>
  );
}
