import { Check, LoaderCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { MouseEvent, ReactNode } from "react";
import { useRef } from "react";
import { useTranslation } from "react-i18next";

import { handlePosition } from "@/features/strategies/share-value";
import { cn } from "@/shared/lib/cn";
import { InlineStatus } from "@/shared/ui/InlineStatus";
import { Tooltip } from "@/shared/ui/Tooltip";

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
  /**
   * What sits on the field's own row, after it (the container's Save). The field takes the width that is left
   * and the action keeps the width of its own content.
   */
  action?: ReactNode;
  /**
   * The legend is as tall as its labels, and the stops' 44 px reach 16 px below the slider, into room the container
   * leaves after it (a gap of 16 px or more), instead of the slider keeping 24 px of empty room under its labels.
   */
  reachBelow?: boolean;
}

/**
 * The classes of the range input, in one place so a test can read them. The browser keeps the pointer, the
 * touch and the keys; the vendor pseudo-elements give the native thumb a fixed size (it is what the drawing
 * under it is aligned to) and the prototype's look, an `ink` dot ringed in `gain`, and make the native track
 * transparent over the drawing. WebKit does not centre its thumb on a taller track, hence the margin: (44 - 16) / 2.
 */
export const RANGE_CLASS = [
  "relative z-10 m-0 block h-11 w-full cursor-pointer appearance-none bg-transparent p-0",
  "focus-visible:outline-none disabled:cursor-not-allowed",
  "[&::-webkit-slider-runnable-track]:h-11 [&::-webkit-slider-runnable-track]:border-0 [&::-webkit-slider-runnable-track]:bg-transparent",
  "[&::-moz-range-track]:h-11 [&::-moz-range-track]:border-0 [&::-moz-range-track]:bg-transparent",
  "[&::-webkit-slider-thumb]:mt-3.5 [&::-webkit-slider-thumb]:size-4 [&::-webkit-slider-thumb]:appearance-none",
  "[&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-gain [&::-webkit-slider-thumb]:bg-ink",
  "[&::-moz-range-thumb]:box-border [&::-moz-range-thumb]:size-4",
  "[&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-gain [&::-moz-range-thumb]:bg-ink",
  "disabled:[&::-webkit-slider-thumb]:border-rule-strong disabled:[&::-moz-range-thumb]:border-rule-strong",
  "focus-visible:[&::-webkit-slider-thumb]:outline-2 focus-visible:[&::-webkit-slider-thumb]:outline-offset-2 focus-visible:[&::-webkit-slider-thumb]:outline-gain",
  "focus-visible:[&::-moz-range-thumb]:outline-2 focus-visible:[&::-moz-range-thumb]:outline-offset-2 focus-visible:[&::-moz-range-thumb]:outline-gain",
].join(" ");

/**
 * The box of a field in the settings column, as `ex11` and `ex12` draw it (RD.7e): 38 px high, the number at the
 * start and its unit at the end, inside the border. The wrapper carries everything that makes it look like a field;
 * the input has no look of its own and takes the room the unit leaves.
 */
export function fieldBoxClass(invalid: boolean, disabled: boolean): string {
  return cn(
    "flex h-9.5 min-w-0 flex-1 items-center gap-2 rounded-lg border bg-ground px-3 font-mono text-sm text-ink",
    "focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-gain",
    invalid ? "border-loss" : "border-rule",
    disabled ? "cursor-not-allowed opacity-50" : "cursor-text",
  );
}

/** The input of a field box: no look of its own, as wide as the room the unit leaves. */
export const FIELD_INPUT_CLASS =
  "min-w-0 flex-1 border-0 bg-transparent p-0 font-mono text-sm text-ink outline-none disabled:cursor-not-allowed";

/** The unit inside a field box, at its end: quieter than the number, in the sans face. */
export const FIELD_UNIT_CLASS = "shrink-0 font-sans text-[13px] text-ink-3";

/**
 * The confirm button beside a field, drawn as the prototype's `.icon-btn`: a 36 px square in the neutral look, with
 * a check. Its text is its accessible name and its tooltip; it shows a spinner while the request is in flight, and
 * the status region tells a screen reader the news after it (a change of a button's name is not announced).
 */
export function FieldSaveButton({
  label,
  message,
  onClick,
  disabled,
  busy = false,
}: {
  label: string;
  message: string | null;
  onClick: () => void;
  disabled: boolean;
  busy?: boolean;
}) {
  return (
    // One block of the row, as wide as the button: the button, then its status region.
    <div className="flex shrink-0 items-center">
      <FieldIconButton label={label} icon={busy ? LoaderCircle : Check} spin={busy} onClick={onClick} disabled={disabled} />
      <InlineStatus message={message} tone="neutral" />
    </div>
  );
}

/** A 36 px icon button of a field's row (the prototype's `.icon-btn`): the label is its name and its tooltip. */
export function FieldIconButton({
  label,
  icon: Icon,
  onClick,
  disabled = false,
  spin = false,
}: {
  label: string;
  icon: LucideIcon;
  onClick: () => void;
  disabled?: boolean;
  spin?: boolean;
}) {
  return (
    <Tooltip text={label} describes={false} tabbable={false}>
      <button
        type="button"
        aria-label={label}
        onClick={onClick}
        disabled={disabled}
        className="inline-flex size-9 shrink-0 items-center justify-center rounded-lg border border-rule bg-panel text-ink-2 hover:bg-panel-2 disabled:opacity-50"
      >
        <Icon aria-hidden="true" className={cn("size-4", spin && "animate-spin")} />
      </button>
    </Tooltip>
  );
}

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
 * The share control: a field with its percent sign at the end of the box (the prototype's `ex11`/`ex12`, which
 * superseded design § B's sign beside the number). The wrapper carries everything that makes it look like a
 * field, the input has no look of its own and takes the room the sign leaves, and the sign is the input's next
 * sibling.
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
  action,
  reachBelow = false,
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
    <div className="flex flex-col gap-1.5">
      {/* One row: the field takes the width that is left, the action beside it keeps its own. */}
      <div className="flex items-center gap-2">
      <div onMouseDown={focusField} className={fieldBoxClass(invalid, disabled)}>
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
          className={FIELD_INPUT_CLASS}
        />
        <span aria-hidden="true" className={FIELD_UNIT_CLASS}>
          %
        </span>
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
        <div className={cn("pointer-events-none relative z-20 mx-2.5 -mt-3", reachBelow ? "mb-1 h-6" : "h-11")}>
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
