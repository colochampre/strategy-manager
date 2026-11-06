import type { UseQueryResult } from "@tanstack/react-query";
import { useState } from "react";

import type { ShareAmountView } from "@/features/strategies/ShareAmount";
import { parseDraft, readStored, roundToHandle } from "@/features/strategies/share-value";
import type { DraftRefusal } from "@/features/strategies/share-value";
import { useSharePreview } from "@/shared/api/share-preview";
import type { SharePreview } from "@/shared/api/types";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";

/**
 * An edit in progress. `base` is the stored value the edit was made on: once the stored value moves, the
 * edit is stale and is dropped (the rule `AllowedPairsEditor` follows). `text` is exactly what the field
 * holds; `handle` is the last whole position the track was given.
 */
interface Draft {
  base: string;
  text: string;
  handle: number;
}

export const DRAFT_REFUSAL_TEXT: Record<DraftRefusal, string> = {
  "not-a-number": "strategies.detail.share.notNumber",
  "not-above-zero": "strategies.detail.share.outOfRange",
  "above-hundred": "strategies.detail.share.outOfRange",
  "too-many-decimals": "strategies.detail.share.tooManyDecimals",
};

const WHOLE_STEP = /^\d+$/;
/** The pause after the last keystroke before a typed decimal's amount is asked for. */
const ASK_PAUSE_MS = 300;

/**
 * Which amount the field's value asks for, from what the server served (design § C2). The panel multiplies
 * nothing: a whole value from 1 to 100 reads the served table of steps, the stored share reads the first
 * read's `exact`, and no other value has a figure yet. Data first: a background refresh that failed does
 * not hide a figure that is already known.
 */
function amountView(
  value: string | null,
  stored: string,
  preview: UseQueryResult<SharePreview>,
  asked: UseQueryResult<SharePreview>,
  askedFor: string | null,
  leveraged: boolean,
): ShareAmountView {
  if (value === null) return { kind: "none" };
  const covered = isCovered(value, stored);
  // The read that holds this value's amount: the first one, or the one asked for it after the pause.
  const read = covered ? preview : asked;
  // A typed value waits for its own read: until the pause has passed for exactly this value, there is no
  // figure, and the answer for any other value is never looked at.
  if (!covered && askedFor !== value) return { kind: "loading" };
  const data = read.data;
  if (data === undefined) return read.isError ? { kind: "failed" } : { kind: "loading" };
  if (data.balance === null) return { kind: "noBalance" };
  const staleAt = data.balance.stale ? data.balance.observed_at : null;
  // The server decides whether a figure is under the pool's minimum order; the panel only carries its word.
  // The notional is the server's, served with an exact for this very share and only above 1x. The stored
  // share's read carries it, and so does the read asked for any other value once its pause has passed.
  const notionalOf = (source: UseQueryResult<SharePreview>): string | null => {
    const exact = source.data?.exact;
    return exact !== undefined && exact !== null && readStored(exact.share) === value ? (exact.notional ?? null) : null;
  };
  const notional = leveraged ? (notionalOf(preview) ?? (askedFor === value ? notionalOf(asked) : null)) : null;
  const known = (amount: string, below: boolean): ShareAmountView => ({
    kind: "known",
    amount,
    currency: data.currency,
    staleAt,
    belowMinimum: below ? data.pool_minimum : null,
    notional,
  });

  const step = WHOLE_STEP.test(value) ? data.steps[Number(value) - 1] : undefined;
  if (step !== undefined) return known(step.amount, step.below_pool_minimum);
  // An answer counts only when it is for the share asked, compared in plain form.
  if (data.exact !== null && readStored(data.exact.share) === value) {
    return known(data.exact.amount, data.exact.below_pool_minimum);
  }
  // The stored share's read is for another share: a save just moved it, and the re-read is on its way.
  return covered && read.isFetching ? { kind: "loading" } : { kind: "failed" };
}

/** Whether a served table already holds the amount of a value: a whole step from 1 to 100, or the stored share. */
function isCovered(value: string, stored: string): boolean {
  return value === stored || (WHOLE_STEP.test(value) && Number(value) >= 1 && Number(value) <= 100);
}

/**
 * A share being edited over `stored`: the text as typed, the handle that follows it, and the amount the server
 * serves for it. The value is one decimal string, and nothing is sent from here. Moving the handle or activating
 * a stop is the one moment a decimal is rounded, to a whole number. `onEdit` runs on any movement of the control.
 * `leverage` is the one the share will open at (the seat's, or the one chosen in the same form): above 1 the
 * reads carry it, so the server serves the notional beside the margin, and a whole step, which has no
 * notional, is also read by itself once its pause has passed. At 1x nothing is asked beyond what always was.
 */
export function useShareDraft(strategyId: string, stored: string | null, onEdit?: () => void, leverage = 1) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const leveraged = leverage > 1;
  const askedLeverage = leveraged ? leverage : undefined;
  const preview = useSharePreview(strategyId, undefined, askedLeverage);

  const current = stored !== null && draft !== null && draft.base === stored ? draft : null;
  const text = current?.text ?? stored ?? "";
  const reading = parseDraft(text);
  // A value no served table covers: not a whole step and not the stored share. It is read once, by itself.
  // Above 1x a whole step is read too, for its notional (the table of steps has none); the stored share's own
  // read already carries it.
  const wanted =
    stored !== null && reading.valid && (leveraged ? reading.canonical !== stored : !isCovered(reading.canonical, stored))
      ? reading.canonical
      : null;
  // Asked 300 ms after the last keystroke, so a number typed digit by digit sends one request, for the last.
  const askedFor = useDebouncedValue(wanted, ASK_PAUSE_MS);
  const asked = useSharePreview(strategyId, askedFor ?? undefined, askedLeverage);

  const handle = current?.handle ?? (stored === null ? 1 : roundToHandle(stored));
  const amount: ShareAmountView =
    stored === null ? { kind: "none" } : amountView(reading.valid ? reading.canonical : null, stored, preview, asked, askedFor, leveraged);

  const edit = (next: string, nextHandle: number) => {
    onEdit?.();
    setDraft({ base: stored ?? "", text: next, handle: nextHandle });
  };
  const changeText = (next: string) => {
    const read = parseDraft(next);
    edit(next, read.valid ? roundToHandle(read.canonical) : handle);
  };
  const changeStep = (step: number) => edit(String(step), step);

  return {
    text,
    reading,
    handle,
    amount,
    /** Whether the user has moved the control since the stored value was last the starting point. */
    edited: current !== null,
    // When the balance was read, from the first read; there is no time to name until a balance exists.
    readAt: preview.data?.balance?.observed_at ?? null,
    changeText,
    changeStep,
  };
}
