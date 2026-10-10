import type { MouseEvent } from "react";
import { useRef } from "react";
import { useTranslation } from "react-i18next";

import { handlePosition } from "@/features/strategies/share-value";
import { cn } from "@/shared/lib/cn";

/** What the control draws and tells its container. Presentational: it holds no state and sends nothing. */
export interface ShareSliderProps {
  /** The id of the field, so the visible label can point at it. */
  fieldId: string;
  /** The id of the visible label, which names the track as well. */
  labelId: string;
  /** The field's text exactly as typed. */
  text: string;
  /** The handle's whole step, 1 to 100. */
  handle: number;
  /** The share the text reads as, in canonical form, or `null` when the text is not a value. */
  value: string | null;
  disabled: boolean;
  invalid: boolean;
  /** The id of the validation text that explains `invalid`, when one shows. */
  describedBy?: string | undefined;
  onText: (text: string) => void;
  onHandle: (step: number) => void;
  onStop: (stop: number) => void;
}

/**
 * The classes of the range input, in one place so a test can read them. The browser keeps the pointer, the
 * touch and the keys; the vendor pseudo-elements give the native thumb a fixed size (it is what the drawing
 * under it is aligned to) and the `gain` colour, and make the native track transparent over the drawing.
 * WebKit does not centre its thumb on a taller track, hence the margin: (44 - 20) / 2.
 */
export const RANGE_CLASS = [
  "relative z-10 m-0 block h-11 w-full cursor-pointer appearance-none bg-transparent p-0",
  "focus-visible:outline-none disabled:cursor-not-allowed",
  "[&::-webkit-slider-runnable-track]:h-11 [&::-webkit-slider-runnable-track]:border-0 [&::-webkit-slider-runnable-track]:bg-transparent",
  "[&::-moz-range-track]:h-11 [&::-moz-range-track]:border-0 [&::-moz-range-track]:bg-transparent",
  "[&::-webkit-slider-thumb]:mt-3 [&::-webkit-slider-thumb]:size-5 [&::-webkit-slider-thumb]:appearance-none",
  "[&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-panel [&::-webkit-slider-thumb]:bg-gain",
  "[&::-moz-range-thumb]:box-border [&::-moz-range-thumb]:size-5",
  "[&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-panel [&::-moz-range-thumb]:bg-gain",
  "disabled:[&::-webkit-slider-thumb]:bg-rule-strong disabled:[&::-moz-range-thumb]:bg-rule-strong",
  "focus-visible:[&::-webkit-slider-thumb]:outline-2 focus-visible:[&::-webkit-slider-thumb]:outline-offset-2 focus-visible:[&::-webkit-slider-thumb]:outline-gain",
  "focus-visible:[&::-moz-range-thumb]:outline-2 focus-visible:[&::-moz-range-thumb]:outline-offset-2 focus-visible:[&::-moz-range-thumb]:outline-gain",
].join(" ");

/**
 * The four stops, each with the one fixed class that places it: Tailwind reads class names from the source,
 * so a position computed at run time would never reach the stylesheet. Each class is `left-[` the position
 * `share-value.ts` gives for that step `]`, and a test holds the two to each other.
 */
const STOPS = [
  { stop: 25, place: "left-[24.2424%]" },
  { stop: 50, place: "left-[49.4949%]" },
  { stop: 75, place: "left-[74.7475%]" },
  { stop: 100, place: "left-[100%]" },
] as const;

const TRACK_FIRST_STEP = 1;
const TRACK_LAST_STEP = 100;

/** The longest text the field takes: a bound on the text, not a rule about the number. */
const FIELD_MAX_LENGTH = 12;

/**
 * The share control: a field with its percent sign together at the left (design § B). The wrapper carries
 * everything that makes it look like a field, the input has no look of its own, and the sign is the input's
 * next sibling: the input is as wide as its text where the browser can size it to its text
 * (`field-sizing`), and by its `size` attribute where it cannot, so the sign follows the last character.
 */
export function ShareSlider({
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
}: ShareSliderProps) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);

  // A press anywhere in the wrapper puts the caret in the input. The wrapper is not a second label, which
  // would join the field's name. A press on the input itself is left to the browser.
  const focusField = (event: MouseEvent<HTMLDivElement>) => {
    const input = inputRef.current;
    if (input === null || disabled || event.target === input) return;
    event.preventDefault();
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  };

  return (
    <div className="flex flex-col gap-3">
      <div
        onMouseDown={focusField}
        className={cn(
          "flex min-h-11 w-full items-center rounded-md border bg-ground px-3 font-mono text-sm text-ink",
          "focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-gain",
          invalid ? "border-loss" : "border-rule",
          disabled ? "cursor-not-allowed opacity-50" : "cursor-text",
        )}
      >
        <input
          ref={inputRef}
          id={fieldId}
          type="text"
          inputMode="decimal"
          maxLength={FIELD_MAX_LENGTH}
          autoComplete="off"
          size={Math.max(1, text.length)}
          value={text}
          disabled={disabled}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          onChange={(event) => onText(event.target.value)}
          className="field-sizing-content min-w-[1ch] border-0 bg-transparent pr-0.5 font-mono text-sm text-ink outline-none disabled:cursor-not-allowed"
        />
        <span aria-hidden="true" className="text-ink">
          %
        </span>
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
              x2={handlePosition(handle)}
              y1="50%"
              y2="50%"
              strokeWidth="4"
              strokeLinecap="round"
              className={disabled ? "stroke-rule-strong" : "stroke-gain"}
            />
            {STOPS.map(({ stop }) => (
              <circle
                key={stop}
                cx={handlePosition(stop)}
                cy="50%"
                r="5"
                strokeWidth="2"
                className={cn("stroke-panel", stop <= handle && !disabled ? "fill-gain" : "fill-rule-strong")}
              />
            ))}
          </svg>
          <input
            type="range"
            min={TRACK_FIRST_STEP}
            max={TRACK_LAST_STEP}
            step={1}
            value={handle}
            disabled={disabled}
            aria-labelledby={labelId}
            aria-valuetext={t("strategies.detail.share.valueText", { value: value ?? String(handle) })}
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
              aria-label={t("strategies.detail.share.stop", { value: stop })}
              aria-pressed={value === String(stop)}
              onClick={() => onStop(stop)}
              className={cn(
                "pointer-events-auto absolute top-0 flex size-11 -translate-x-1/2 cursor-pointer items-start justify-center",
                "focus-visible:outline-2 focus-visible:outline-gain disabled:cursor-not-allowed disabled:opacity-50",
                place,
              )}
            >
              <span
                className={cn(
                  "block px-1 pt-1 font-mono text-xs leading-4",
                  value === String(stop) ? "text-ink" : "text-ink-3",
                )}
              >
                {stop}%
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
