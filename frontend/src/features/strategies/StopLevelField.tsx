import { useId, useRef, type MouseEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { FIELD_NAME_CLASS, type FieldNameLook } from "@/features/strategies/field-name";
import { maxLeverage, readStopLevel } from "@/features/strategies/stop-level";
import { cn } from "@/shared/lib/cn";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";

interface StopLevelFieldProps {
  /** The level as typed. */
  value: string;
  onChange: (text: string) => void;
  disabled: boolean;
  /** How the name reads: a dialog's field, or a section of the strategy page. Default: a dialog's field. */
  look?: FieldNameLook;
  /** Placed on the field's row, beside it, as wide as it needs: the page's Save. */
  action?: ReactNode;
  /** Whether to say what the level caps the leverage at. The page says it in its leverage section. Default: yes. */
  showCap?: boolean;
}

/**
 * The stop level's field: a percentage of price as typed, what it caps the leverage at, and why it is refused
 * when it is. Presentational: the container keeps the text and decides what to send.
 */
export function StopLevelField({
  value,
  onChange,
  disabled,
  look = "field",
  action,
  showCap = true,
}: StopLevelFieldProps) {
  const { t } = useTranslation();
  const ids = { field: useId(), problem: useId() };
  const inputRef = useRef<HTMLInputElement>(null);
  const info = useInfoDisclosure();
  const reading = readStopLevel(value);

  // The input is as wide as its text, so a press anywhere in the box puts the caret in it, at the end. The box is
  // not a second label, which would join the field's name. A press on the input itself is left to the browser.
  const focusField = (event: MouseEvent<HTMLDivElement>) => {
    const input = inputRef.current;
    if (input === null || disabled || event.target === input) return;
    event.preventDefault();
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  };

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start">
        <label htmlFor={ids.field} className={FIELD_NAME_CLASS[look]}>
          {t("strategies.stopLevel.label")}
        </label>
        <InfoButton disclosure={info} label={t("strategies.stopLevel.info")} />
      </div>
      <InfoText disclosure={info}>
        <p className="text-xs text-ink-3">{t("strategies.stopLevel.hint")}</p>
      </InfoText>
      {/* One row: the field takes the width that is left, the action beside it keeps its own. */}
      <div className="flex items-start gap-x-3">
        <div
          onMouseDown={focusField}
          className={cn(
            "flex min-h-11 min-w-0 flex-1 items-center rounded-md border bg-ground px-3 font-mono text-sm text-ink",
            "focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-gain",
            reading.valid ? "border-rule" : "border-loss",
            disabled ? "cursor-not-allowed opacity-50" : "cursor-text",
          )}
        >
          <input
            ref={inputRef}
            id={ids.field}
            type="text"
            inputMode="decimal"
            autoComplete="off"
            maxLength={8}
            size={Math.max(1, value.length)}
            value={value}
            disabled={disabled}
            aria-invalid={!reading.valid}
            aria-describedby={reading.valid ? undefined : ids.problem}
            onChange={(event) => onChange(event.target.value)}
            className="field-sizing-content min-w-[1ch] border-0 bg-transparent pr-0.5 font-mono text-sm text-ink outline-none disabled:cursor-not-allowed"
          />
          <span aria-hidden="true" className="text-ink">
            {t("strategies.stopLevel.unit")}
          </span>
        </div>
        {action}
      </div>
      {!reading.valid ? (
        <p id={ids.problem} className="text-xs text-loss">
          {t("strategies.stopLevel.invalid")}
        </p>
      ) : (
        showCap && (
          <p className="text-xs text-ink-3">{t("strategies.stopLevel.cap", { max: maxLeverage(reading.canonical) })}</p>
        )
      )}
    </div>
  );
}
