import type { UseQueryResult } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { InlineStatus } from "@/features/strategies/InlineStatus";
import { ShareAmount } from "@/features/strategies/ShareAmount";
import type { ShareAmountView } from "@/features/strategies/ShareAmount";
import { ShareSlider } from "@/features/strategies/ShareSlider";
import { parseDraft, readStored, roundToHandle } from "@/features/strategies/share-value";
import type { DraftRefusal } from "@/features/strategies/share-value";
import { ApiError } from "@/shared/api/client";
import { useSharePreview } from "@/shared/api/share-preview";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";
import { useSetAllocationPercent } from "@/shared/api/strategies";
import type { SharePreview, Strategy } from "@/shared/api/types";

interface PoolShareEditorProps {
  strategy: Strategy;
}

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

const REFUSAL_TEXT: Record<DraftRefusal, string> = {
  "not-a-number": "strategies.detail.share.notNumber",
  "not-above-zero": "strategies.detail.share.outOfRange",
  "above-hundred": "strategies.detail.share.outOfRange",
  "too-many-decimals": "strategies.detail.share.tooManyDecimals",
};

/** The text of a refused or failed save: the status (and the archived code) decides, never the server's wording. */
function saveRefusal(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) return "strategies.detail.share.outOfRange";
    if (error.status === 409 && error.code === "STRATEGY_ARCHIVED") return "strategies.detail.share.archived";
    if (error.status === 404) return "strategies.detail.share.gone";
  }
  return "strategies.detail.share.saveFailed";
}

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
  const known = (amount: string): ShareAmountView => ({ kind: "known", amount, currency: data.currency, staleAt });

  const step = WHOLE_STEP.test(value) ? data.steps[Number(value) - 1] : undefined;
  if (step !== undefined) return known(step.amount);
  // An answer counts only when it is for the share asked, compared in plain form.
  if (data.exact !== null && readStored(data.exact.share) === value) return known(data.exact.amount);
  // The stored share's read is for another share: a save just moved it, and the re-read is on its way.
  return covered && read.isFetching ? { kind: "loading" } : { kind: "failed" };
}

/** Whether a served table already holds the amount of a value: a whole step from 1 to 100, or the stored share. */
function isCovered(value: string, stored: string): boolean {
  return value === stored || (WHOLE_STEP.test(value) && Number(value) >= 1 && Number(value) <= 100);
}

/**
 * The share of the pool a strategy asks for per trade (design § C). The value is one decimal string: the
 * field keeps the text as typed, the handle follows it, and nothing is sent until Save. Moving the handle
 * or activating a stop is the one moment a decimal is rounded, to a whole number.
 */
export function PoolShareEditor({ strategy }: PoolShareEditorProps) {
  const { t } = useTranslation();
  const ids = { field: useId(), label: useId(), problem: useId() };
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saved, setSaved] = useState(false);
  const save = useSetAllocationPercent(strategy.id);
  const preview = useSharePreview(strategy.id);

  const stored = readStored(strategy.allocation_percent);
  const current = stored !== null && draft !== null && draft.base === stored ? draft : null;
  const text = current?.text ?? stored ?? "";
  const reading = parseDraft(text);
  // A value no served table covers: not a whole step and not the stored share. It is read once, by itself.
  const wanted = stored !== null && reading.valid && !isCovered(reading.canonical, stored) ? reading.canonical : null;
  // Asked 300 ms after the last keystroke, so a number typed digit by digit sends one request, for the last.
  const askedFor = useDebouncedValue(wanted, ASK_PAUSE_MS);
  const asked = useSharePreview(strategy.id, askedFor ?? undefined);
  if (stored === null) {
    // Never a guess: a stored value that is not a plain decimal gets no track, no field and no Save.
    return (
      <section className="flex flex-col gap-3">
        <p className="text-sm text-ink-2">{t("strategies.detail.share.label")}</p>
        <p className="text-sm text-ink-2">{t("strategies.detail.share.unreadable")}</p>
      </section>
    );
  }

  const archived = strategy.archived_at !== null;
  const handle = current?.handle ?? roundToHandle(stored);
  const changed = reading.valid && reading.canonical !== stored;
  const busy = save.isPending;
  const amount = amountView(reading.valid ? reading.canonical : null, stored, preview, asked, askedFor);

  // Any movement of this control ends "Saved": a handle moved, a stop activated, a key typed. No timer.
  const edit = (next: string, nextHandle: number) => {
    setSaved(false);
    setDraft({ base: stored, text: next, handle: nextHandle });
  };
  const handleText = (next: string) => {
    const read = parseDraft(next);
    edit(next, read.valid ? roundToHandle(read.canonical) : handle);
  };
  const handleStep = (step: number) => edit(String(step), step);

  const handleSave = () => {
    if (!reading.valid || !changed || archived || busy) return;
    // Cleared before the request is sent, so a refusal and "Saved" are never on screen together; set on
    // success only, never on settle.
    setSaved(false);
    save.mutate(reading.canonical, { onSuccess: () => setSaved(true) });
  };

  return (
    <section className="flex flex-col gap-3">
      <label id={ids.label} htmlFor={ids.field} className="text-sm text-ink-2">
        {t("strategies.detail.share.label")}
      </label>
      <ShareSlider
        fieldId={ids.field}
        labelId={ids.label}
        text={text}
        handle={handle}
        value={reading.valid ? reading.canonical : null}
        disabled={archived || busy}
        invalid={!reading.valid}
        describedBy={reading.valid ? undefined : ids.problem}
        onText={handleText}
        onHandle={handleStep}
        onStop={handleStep}
      />
      <ShareAmount view={amount} />
      {!reading.valid && (
        <p id={ids.problem} className="text-xs text-loss">
          {t(REFUSAL_TEXT[reading.refusal])}
        </p>
      )}
      {save.status === "error" && (
        <p role="alert" className="text-sm text-loss">
          {t(saveRefusal(save.error))}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <button
          type="button"
          onClick={handleSave}
          disabled={archived || busy || !changed}
          className="min-h-11 rounded-md bg-gain px-3 text-sm font-medium text-ground hover:opacity-90 disabled:opacity-50"
        >
          {busy ? t("strategies.detail.share.saving") : t("strategies.detail.share.save")}
        </button>
        <InlineStatus message={saved ? t("strategies.detail.saved") : null} />
      </div>
    </section>
  );
}
