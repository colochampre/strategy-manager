import type { MouseEvent, ReactNode } from "react";
import { useRef } from "react";
import { useTranslation } from "react-i18next";

import { RANGE_CLASS } from "@/features/strategies/ShareSlider";
import { FIRST_LEVERAGE, LAST_LEVERAGE, leveragePosition } from "@/features/strategies/leverage-value";
import { cn } from "@/shared/lib/cn";

/** What the control draws and tells its container. Presentational: it holds no state and sends nothing. */
export interface LeverageSliderProps {
  /** The id of the field, so the visible label can point at it. */
  fieldId: string;
  /** The id of the visible label, which names the track as well. */
  labelId: string;
  /** The field's text exactly as typed. */
  text: string;
  /** The handle's whole step, 1 to 20. */
  handle: number;
  /** The leverage the text reads as, or `null` when the text is not a value. */
  value: number | null;
  disabled: boolean;
  invalid: boolean;
  /** The id of the validation text that explains `invalid`, when one shows. */
  describedBy?: string | undefined;
  onText: (text: string) => void;
  onHandle: (step: number) => void;
  onStop: (stop: number) => void;
  /** What sits on the field's own row, after it (the container's Save); the field takes the width that is left. */
  action?: ReactNode;
}

/**
 * The four stops, each with the one fixed class that places it: Tailwind reads class names from the source,
 * so a position computed at run time would never reach the stylesheet. Each class is `left-[` the position
 * `leverage-value.ts` gives for that step `]`, and a test holds the two to each other.
 */
const STOPS = [
  { stop: 5, place: "left-[21.0526%]" },
  { stop: 10, place: "left-[47.3684%]" },
  { stop: 15, place: "left-[73.6842%]" },
  { stop: 20, place: "left-[100%]" },
] as const;

/** The longest text the field takes: a bound on the text (room for stray spaces), not a rule about the number. */
const FIELD_MAX_LENGTH = 4;

/**
 * The leverage control, built like `ShareSlider`: a field with its "x" sign together at the left, so the
 * value reads "x5", and a range from 1 to 20 with four stops under it. The wrapper carries everything that
 * makes it look like a field; the sign comes before the input and is not part of the text.
 */
export function LeverageSlider({
  fieldId,
  labelId,
  text,
  handle,
  value,
  disabled,
  invalid,
  describedBy,
  onText,
  onHandle,
  onStop,
  action,
}: LeverageSliderProps) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);

  // A press anywhere in the wrapper puts the caret in the input. A press on the input itself is left to the browser.
  const focusField = (event: MouseEvent<HTMLDivElement>) => {
    const input = inputRef.current;
    if (input === null || disabled || event.target === input) return;
    event.preventDefault();
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  };

  return (
    <div className="flex flex-col gap-3">
      {/* One row: the field takes the width that is left, the action beside it keeps its own. */}
      <div className="flex items-start gap-x-3">
      <div
        onMouseDown={focusField}
        className={cn(
          "flex min-h-11 min-w-0 flex-1 items-center rounded-md border bg-ground px-3 font-mono text-sm text-ink",
          "focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-gain",
          invalid ? "border-loss" : "border-rule",
          disabled ? "cursor-not-allowed opacity-50" : "cursor-text",
        )}
      >
        <span aria-hidden="true" className="pr-0.5 text-ink">
          x
        </span>
        <input
          ref={inputRef}
          id={fieldId}
          type="text"
          inputMode="numeric"
          maxLength={FIELD_MAX_LENGTH}
          autoComplete="off"
          size={Math.max(1, text.length)}
          value={text}
          disabled={disabled}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          onChange={(event) => onText(event.target.value)}
          className="field-sizing-content min-w-[1ch] border-0 bg-transparent font-mono text-sm text-ink outline-none disabled:cursor-not-allowed"
        />
      </div>
      {action}
      </div>
      <div>
        <div className="relative h-11">
          <svg
            aria-hidden="true"
            focusable="false"
            className="pointer-events-none absolute inset-y-0 left-2.5 h-11 w-[calc(100%-1.25rem)] overflow-visible"
          >
            <line x1="0%" x2="100%" y1="50%" y2="50%" strokeWidth="4" strokeLinecap="round" className="stroke-rule" />
            <line
              x1="0%"
              x2={leveragePosition(handle)}
              y1="50%"
              y2="50%"
              strokeWidth="4"
              strokeLinecap="round"
              className={disabled ? "stroke-rule-strong" : "stroke-gain"}
            />
            {STOPS.map(({ stop }) => (
              <circle
                key={stop}
                cx={leveragePosition(stop)}
                cy="50%"
                r="5"
                strokeWidth="2"
                className={cn("stroke-panel", stop <= handle && !disabled ? "fill-gain" : "fill-rule-strong")}
              />
            ))}
          </svg>
          <input
            type="range"
            min={FIRST_LEVERAGE}
            max={LAST_LEVERAGE}
            step={1}
            value={handle}
            disabled={disabled}
            aria-labelledby={labelId}
            aria-valuetext={t("strategies.leverage.valueText", { value: value ?? String(handle) })}
            onChange={(event) => onHandle(Number(event.target.value))}
            className={RANGE_CLASS}
          />
        </div>
        {/* The legend is pulled up 12 px so it begins at the handle's lower edge; it lets presses through
            and only its buttons take them, so none covers the handle. */}
        <div className="pointer-events-none relative z-20 mx-2.5 -mt-3 h-11">
          {STOPS.map(({ stop, place }) => (
            <button
              key={stop}
              type="button"
              disabled={disabled}
              aria-label={t("strategies.leverage.stop", { value: stop })}
              aria-pressed={value === stop}
              onClick={() => onStop(stop)}
              className={cn(
                "pointer-events-auto absolute top-0 flex size-11 -translate-x-1/2 cursor-pointer items-start justify-center",
                "focus-visible:outline-2 focus-visible:outline-gain disabled:cursor-not-allowed disabled:opacity-50",
                place,
              )}
            >
              <span
                className={cn("block px-1 pt-1 font-mono text-xs leading-4", value === stop ? "text-ink" : "text-ink-3")}
              >
                x{stop}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
