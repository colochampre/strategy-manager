import { useId } from "react";
import { useTranslation } from "react-i18next";

import { DESCRIPTION_MAX, readDescription } from "@/features/strategies/description-value";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";

interface DescriptionFieldProps {
  value: string;
  onChange: (text: string) => void;
  /** Held still: a request is in flight, or the strategy takes no change. */
  disabled?: boolean;
}

/**
 * The author's free text about a strategy: a multi-line field with an information disclosure, a counter of
 * characters as the server counts them, and the refusal in words when it is over the limit. It holds no state of
 * its own and sends nothing; the dialog and the strategy page each decide when to send.
 */
export function DescriptionField({ value, onChange, disabled = false }: DescriptionFieldProps) {
  const { t } = useTranslation();
  const ids = { field: useId(), problem: useId() };
  const info = useInfoDisclosure();
  const reading = readDescription(value);
  const tooLong = !reading.blank && reading.tooLong;
  const length = reading.blank ? 0 : reading.length;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start">
        <label htmlFor={ids.field} className="text-xs font-semibold leading-5 text-ink-2">
          {t("strategies.description.label")}
        </label>
        <InfoButton disclosure={info} label={t("strategies.description.info")} />
        <p className={`ml-auto font-mono text-xs leading-5 ${tooLong ? "text-loss" : "text-ink-3"}`}>
          {t("strategies.description.counter", { length, max: DESCRIPTION_MAX })}
        </p>
      </div>
      <InfoText disclosure={info}>
        <p className="text-xs text-ink-3">{t("strategies.description.hint")}</p>
      </InfoText>
      <textarea
        id={ids.field}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        rows={4}
        aria-invalid={tooLong}
        aria-describedby={tooLong ? ids.problem : undefined}
        className="rounded-md border border-rule bg-ground px-3 py-2 text-sm text-ink disabled:opacity-50"
      />
      {tooLong && (
        <p id={ids.problem} className="text-xs text-loss">
          {t("strategies.description.tooLong")}
        </p>
      )}
    </div>
  );
}
