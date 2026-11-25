import type { ReactNode } from "react";

import { cn } from "@/shared/lib/cn";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  /** Drawn before the label, 16 px; decorative. */
  icon?: ReactNode;
}

interface SegmentedProps<T extends string> {
  /** The group's accessible name. */
  label: string;
  options: readonly SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
}

/**
 * The prototype's `.seg.big` (ex7): two or three options in a rounded track, the one in force lifted on `panel-2`
 * with a 1 px strong rule. A radio group, so a screen reader hears which one is in force. Pressing the option in
 * force does nothing, and `onChange` says only a move to another one.
 */
export function Segmented<T extends string>({ label, options, value, onChange, disabled = false }: SegmentedProps<T>) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-rule bg-ground p-0.5">
      {options.map((option) => {
        const on = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={disabled}
            onClick={() => {
              if (!on) onChange(option.value);
            }}
            className={cn(
              "inline-flex h-[34px] items-center gap-2 rounded-md px-4 text-sm transition-colors motion-reduce:transition-none disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-gain",
              on ? "bg-panel-2 text-ink ring-1 ring-rule-strong ring-inset" : "text-ink-3 hover:text-ink-2",
            )}
          >
            {option.icon}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
