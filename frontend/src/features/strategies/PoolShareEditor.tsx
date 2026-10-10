import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { InlineStatus } from "@/features/strategies/InlineStatus";
import { ShareSlider } from "@/features/strategies/ShareSlider";
import { parseDraft, readStored, roundToHandle } from "@/features/strategies/share-value";
import type { DraftRefusal } from "@/features/strategies/share-value";
import { ApiError } from "@/shared/api/client";
import { useSetAllocationPercent } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";

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

  const stored = readStored(strategy.allocation_percent);
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
  const current = draft !== null && draft.base === stored ? draft : null;
  const text = current?.text ?? stored;
  const handle = current?.handle ?? roundToHandle(stored);
  const reading = parseDraft(text);
  const changed = reading.valid && reading.canonical !== stored;
  const busy = save.isPending;

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
