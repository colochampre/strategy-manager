import { useId } from "react";
import { useTranslation } from "react-i18next";

import { maxLeverage, readStopLevel } from "@/features/strategies/stop-level";
import { cn } from "@/shared/lib/cn";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";

interface StopLevelFieldProps {
  /** The level as typed. */
  value: string;
  onChange: (text: string) => void;
  disabled: boolean;
}

/**
 * The stop level's field: a percentage of price as typed, what it caps the leverage at, and why it is refused
 * when it is. Presentational: the container keeps the text and decides what to send.
 */
export function StopLevelField({ value, onChange, disabled }: StopLevelFieldProps) {
  const { t } = useTranslation();
  const ids = { field: useId(), problem: useId() };
  const info = useInfoDisclosure();
  const reading = readStopLevel(value);

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start">
        <label htmlFor={ids.field} className="text-xs font-semibold leading-5 text-ink-2">
          {t("strategies.stopLevel.label")}
        </label>
        <InfoButton disclosure={info} label={t("strategies.stopLevel.info")} />
      </div>
      <InfoText disclosure={info}>
        <p className="text-xs text-ink-3">{t("strategies.stopLevel.hint")}</p>
      </InfoText>
      <div
        className={cn(
          "flex min-h-11 items-center gap-2 rounded-md border bg-ground px-3 font-mono text-sm text-ink",
          "focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-gain",
          reading.valid ? "border-rule" : "border-loss",
          disabled && "cursor-not-allowed opacity-50",
        )}
      >
        <input
          id={ids.field}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          maxLength={8}
          value={value}
          disabled={disabled}
          aria-invalid={!reading.valid}
          aria-describedby={reading.valid ? undefined : ids.problem}
          onChange={(event) => onChange(event.target.value)}
          className="min-w-0 flex-1 border-0 bg-transparent font-mono text-sm text-ink outline-none disabled:cursor-not-allowed"
        />
        <span aria-hidden="true" className="text-ink-3">
          {t("strategies.stopLevel.unit")}
        </span>
      </div>
      {reading.valid ? (
        <p className="text-xs text-ink-3">{t("strategies.stopLevel.cap", { max: maxLeverage(reading.canonical) })}</p>
      ) : (
        <p id={ids.problem} className="text-xs text-loss">
          {t("strategies.stopLevel.invalid")}
        </p>
      )}
    </div>
  );
}
