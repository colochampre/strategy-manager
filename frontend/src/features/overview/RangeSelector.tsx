import { useState } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/shared/lib/cn";

/** The names `ranges[].range` carries on the wire, in the order the selector shows them. */
export const RANGES = ["7D", "30D", "90D", "1Y", "All"] as const;
export type RangeName = (typeof RANGES)[number];
export const DEFAULT_RANGE: RangeName = "30D";

interface RangeSelectorProps {
  /** Controlled value. Left out, the selector keeps its own, starting at 30D. */
  value?: RangeName;
  onChange: (range: RangeName) => void;
}

/**
 * Picks which of the pool's range summaries the ledger line shows. It never
 * rebases the return chart, which always draws the whole series.
 */
export function RangeSelector({ value, onChange }: RangeSelectorProps) {
  const { t } = useTranslation();
  const [own, setOwn] = useState<RangeName>(DEFAULT_RANGE);
  const selected = value ?? own;

  return (
    <div
      role="group"
      aria-label={t("overview.range.label")}
      className="flex overflow-hidden rounded-md border border-rule"
    >
      {RANGES.map((range) => (
        <button
          key={range}
          type="button"
          aria-pressed={range === selected}
          onClick={() => {
            setOwn(range);
            onChange(range);
          }}
          className={cn(
            "min-h-11 min-w-11 px-3.5 font-mono text-xs focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-gain",
            range === selected ? "bg-panel-2 text-ink" : "bg-transparent text-ink-2",
          )}
        >
          {t(`overview.range.${range}`)}
        </button>
      ))}
    </div>
  );
}
