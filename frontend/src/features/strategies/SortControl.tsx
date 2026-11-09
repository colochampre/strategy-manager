import { ArrowDown, ArrowUp } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SORT_KEYS } from "@/features/strategies/card-sort";
import type { CardSort, SortKey } from "@/features/strategies/card-sort";
import { cn } from "@/shared/lib/cn";

interface SortControlProps {
  sort: CardSort;
  /** The key the reader chose; the owner decides what choosing the active key again does (`nextSort`). */
  onChange: (key: SortKey) => void;
}

/**
 * What a list of cards is ordered by: one button per figure, the active one pressed and drawn with an arrow for
 * its direction, which assistive tech hears in the button's name.
 */
export function SortControl({ sort, onChange }: SortControlProps) {
  const { t } = useTranslation();

  return (
    <div role="group" aria-label={t("strategies.sort.label")} className="flex flex-wrap items-center gap-1.5">
      <span aria-hidden="true" className="text-xs text-ink-3">
        {t("strategies.sort.label")}
      </span>
      {SORT_KEYS.map((key) => {
        const active = sort.key === key;
        const label = t(`strategies.sort.${key}`);
        const Arrow = sort.direction === "desc" ? ArrowDown : ArrowUp;
        return (
          <button
            key={key}
            type="button"
            aria-pressed={active}
            aria-label={
              active
                ? t("strategies.sort.active", {
                    key: label,
                    direction: t(sort.direction === "desc" ? "strategies.sort.descending" : "strategies.sort.ascending"),
                  })
                : undefined
            }
            onClick={() => onChange(key)}
            className={cn(
              "inline-flex min-h-9 items-center gap-1 rounded-md border px-2.5 text-xs",
              active ? "border-gain text-gain" : "border-rule text-ink-2 hover:bg-panel-2",
            )}
          >
            {label}
            {active && <Arrow aria-hidden="true" className="size-3.5" />}
          </button>
        );
      })}
    </div>
  );
}
