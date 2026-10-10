import type { MouseEvent } from "react";
import { useRef } from "react";

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
  describedBy?: string;
  onText: (text: string) => void;
  onHandle: (step: number) => void;
  onStop: (stop: number) => void;
}

/** The classes of the range input, in one place so a test can read them. */
export const RANGE_CLASS = "appearance-none";

/** The longest text the field takes: a bound on the text, not a rule about the number. */
const FIELD_MAX_LENGTH = 12;

/**
 * The share control: a field with its percent sign together at the left (design § B). The wrapper carries
 * everything that makes it look like a field, the input has no look of its own, and the sign is the input's
 * next sibling: the input is as wide as its text where the browser can size it to its text
 * (`field-sizing`), and by its `size` attribute where it cannot, so the sign follows the last character.
 */
export function ShareSlider({ fieldId, text, disabled, invalid, describedBy, onText }: ShareSliderProps) {
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
      <input type="range" />
    </div>
  );
}
