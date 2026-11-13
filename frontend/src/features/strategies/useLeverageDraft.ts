import { useState } from "react";

import { LAST_LEVERAGE, parseLeverage } from "@/features/strategies/leverage-value";
import type { LeverageReading, LeverageRefusal } from "@/features/strategies/leverage-value";

/** The one text that explains any refusal of the field: a whole number from 1 to 20. */
export const LEVERAGE_REFUSAL_TEXT: Record<LeverageRefusal, string> = {
  "not-a-whole-number": "strategies.leverage.invalid",
  "out-of-range": "strategies.leverage.invalid",
};

/**
 * The text and values that explain a refused leverage. Under a stop level's cap below 20 a value above it is
 * said with the cap, so the reader learns what the strategy allows and not only that 20 is the ceiling.
 */
export function leverageProblem(
  refusal: LeverageRefusal,
  max: number,
): { key: string; values: Record<string, number> } {
  if (refusal === "out-of-range" && max < LAST_LEVERAGE) return { key: "strategies.leverage.aboveCap", values: { max } };
  return { key: LEVERAGE_REFUSAL_TEXT[refusal], values: {} };
}

/**
 * An edit in progress. `base` is the stored value the edit was made on: once the stored value moves, the
 * edit is stale and is dropped (the rule `useShareDraft` follows). `text` is exactly what the field holds;
 * `handle` is the last valid whole step the track was given.
 */
interface Draft {
  base: number;
  text: string;
  handle: number;
}

export interface LeverageDraft {
  text: string;
  reading: LeverageReading;
  handle: number;
  changeText: (text: string) => void;
  changeStep: (step: number) => void;
}

/**
 * The leverage field's state: the typed text, what it reads as, and the handle. The handle follows the text
 * while it is a value and stays where it was while it is not. `onEdit` runs on every change the user makes,
 * so a container can end its "Saved".
 */
export function useLeverageDraft(stored: number, onEdit?: () => void, max: number = LAST_LEVERAGE): LeverageDraft {
  const [draft, setDraft] = useState<Draft | null>(null);
  const current: Draft = draft !== null && draft.base === stored ? draft : { base: stored, text: String(stored), handle: stored };

  const changeText = (text: string) => {
    const reading = parseLeverage(text, max);
    setDraft({ base: stored, text, handle: reading.valid ? reading.value : current.handle });
    onEdit?.();
  };
  const changeStep = (requested: number) => {
    // A step above the cap is never taken: the control stops at it.
    const step = Math.min(requested, max);
    setDraft({ base: stored, text: String(step), handle: step });
    onEdit?.();
  };

  return { text: current.text, reading: parseLeverage(current.text, max), handle: current.handle, changeText, changeStep };
}
