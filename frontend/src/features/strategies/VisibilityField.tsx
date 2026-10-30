import { Globe, Lock } from "lucide-react";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import type { Visibility } from "@/shared/api/types";

const VISIBILITIES: readonly Visibility[] = ["PRIVATE", "PUBLIC"];

interface VisibilityFieldProps {
  value: Visibility;
  onChange: (value: Visibility) => void;
  disabled?: boolean;
  /** The class of the select, so the dialog and the page each keep their own field look. It leaves room on
   * the left for the icon. */
  selectClass: string;
  /** Beside a heading: the label and the hint stay for assistive technology and the hint shows on hover, so
   * the select fits the heading's row. */
  compact?: boolean;
}

/**
 * Who may subscribe to a strategy: its select, with the current value's icon (a lock for private, a globe
 * for public) and the hint. Shared by the create dialog and the strategy page, so the two say the same thing
 * in the same words. Private comes first because it is the default (decision 21). A native option cannot
 * draw an icon, so the icon is the selected value's, drawn over the select's left edge.
 */
export function VisibilityField({
  value,
  onChange,
  disabled = false,
  selectClass,
  compact = false,
}: VisibilityFieldProps) {
  const { t } = useTranslation();
  const selectId = useId();
  const hintId = useId();
  const Icon = value === "PUBLIC" ? Globe : Lock;
  const hint = t("strategies.visibility.hint");
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={selectId} className={compact ? "sr-only" : "text-xs font-semibold text-ink-2"}>
        {t("strategies.visibility.label")}
      </label>
      <div className="relative">
        <Icon
          aria-hidden="true"
          className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-2"
        />
        <select
          id={selectId}
          value={value}
          disabled={disabled}
          aria-describedby={hintId}
          title={compact ? hint : undefined}
          onChange={(event) => onChange(event.target.value as Visibility)}
          className={`${selectClass} pl-9`}
        >
          {VISIBILITIES.map((option) => (
            <option key={option} value={option}>
              {t(`strategies.visibility.options.${option}`)}
            </option>
          ))}
        </select>
      </div>
      <p id={hintId} className={compact ? "sr-only" : "text-xs text-ink-3"}>
        {hint}
      </p>
    </div>
  );
}
