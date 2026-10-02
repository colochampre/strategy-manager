import { useId } from "react";
import { useTranslation } from "react-i18next";

interface ArchivedToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
}

/** "Show archived": the list leaves archived strategies out until this is on (spec: Strategies list). */
export function ArchivedToggle({ checked, onChange }: ArchivedToggleProps) {
  const { t } = useTranslation();
  const id = useId();

  return (
    <label htmlFor={id} className="flex min-h-11 cursor-pointer items-center gap-2 text-sm text-ink-2">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="size-4 accent-gain"
      />
      {t("strategies.archivedToggle")}
    </label>
  );
}
