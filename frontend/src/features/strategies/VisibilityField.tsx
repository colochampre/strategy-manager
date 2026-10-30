import { useId } from "react";
import { useTranslation } from "react-i18next";

import type { Visibility } from "@/shared/api/types";

const VISIBILITIES: readonly Visibility[] = ["PRIVATE", "PUBLIC"];

interface VisibilityFieldProps {
  value: Visibility;
  onChange: (value: Visibility) => void;
  disabled?: boolean;
  /** The class of the select, so the dialog and the page each keep their own field look. */
  selectClass: string;
}

/**
 * Who may subscribe to a strategy: its select with the hint under it. Shared by the create dialog and the
 * strategy page, so the two say the same thing in the same words. Private comes first because it is the
 * default (decision 21).
 */
export function VisibilityField({ value, onChange, disabled = false, selectClass }: VisibilityFieldProps) {
  const { t } = useTranslation();
  const selectId = useId();
  const hintId = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={selectId} className="text-xs font-semibold text-ink-2">
        {t("strategies.visibility.label")}
      </label>
      <select
        id={selectId}
        value={value}
        disabled={disabled}
        aria-describedby={hintId}
        onChange={(event) => onChange(event.target.value as Visibility)}
        className={selectClass}
      >
        {VISIBILITIES.map((option) => (
          <option key={option} value={option}>
            {t(`strategies.visibility.options.${option}`)}
          </option>
        ))}
      </select>
      <p id={hintId} className="text-xs text-ink-3">
        {t("strategies.visibility.hint")}
      </p>
    </div>
  );
}
