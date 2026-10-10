import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { InlineStatus } from "@/features/strategies/InlineStatus";
import { PairSelector } from "@/features/strategies/PairSelector";
import type { PairSelectorStatus } from "@/features/strategies/PairSelector";
import { ApiError } from "@/shared/api/client";
import { useAvailablePairs } from "@/shared/api/pairs";
import { useReplaceAllowedPairs } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";

interface AllowedPairsEditorProps {
  strategy: Strategy;
}

/** An edit in progress, and the stored list it was made on: once the stored list moves, the edit is stale. */
interface Draft {
  base: string;
  pairs: string[];
}

const storedKey = (strategy: Strategy) => strategy.allowed_pairs.join(",");

/**
 * The key of the list a save answered, or `null` when the answer holds no list of pairs. The PUT's body is
 * not checked by the hook (which is not changed), so a 200 that is not a strategy must not show "Saved".
 */
function savedKeyOf(answer: Strategy | undefined): string | null {
  const pairs: unknown = answer?.allowed_pairs;
  if (!Array.isArray(pairs) || !pairs.every((pair) => typeof pair === "string")) return null;
  return pairs.join(",");
}

function unknownSymbols(error: ApiError): string[] {
  const unknown = error.fields?.unknown;
  return Array.isArray(unknown) ? unknown.filter((symbol): symbol is string => typeof symbol === "string") : [];
}

/** The refusal's text: the server's `code` decides, as in the new-strategy dialog. */
function saveError(error: unknown): { key: string; values?: Record<string, string> } {
  if (error instanceof ApiError) {
    const symbols = error.code === "UNKNOWN_PAIRS" ? unknownSymbols(error) : [];
    if (symbols.length > 0) return { key: "strategies.pairs.errors.unknown", values: { symbols: symbols.join(", ") } };
    if (error.code === "PAIRS_CHANGED") return { key: "strategies.pairs.errors.changed" };
    if (error.code === "PAIR_CATALOGUE_UNAVAILABLE" || error.status === 502) {
      return { key: "strategies.pairs.errors.venueUnavailable" };
    }
  }
  return { key: "strategies.detail.pairs.saveFailed" };
}

/**
 * Edits a strategy's allowed pairs on top of `PairSelector` (never a free-text
 * field, decision 41), over its own pool's available pairs. Saving sends the
 * FULL set the strategy should end with.
 *
 * - The last pair can be removed on screen but the save stays unavailable: a
 *   strategy with no pair refuses every open.
 * - While the available pairs cannot be read nothing can be ADDED (the selector
 *   offers nothing), but a removal-only save is allowed, because the server
 *   needs no catalogue for a removal.
 * - A stored pair the venue no longer lists stays as a "no longer listed" chip
 *   and is sent back unchanged by any save that does not remove it.
 * - `PAIRS_CHANGED` says so and the stored list is read again; an edit made on
 *   a list that has since moved is dropped, so the operator reviews the stored
 *   list and saves again.
 * - An archived strategy is read-only.
 */
export function AllowedPairsEditor({ strategy }: AllowedPairsEditorProps) {
  const { t } = useTranslation();
  const ids = { pairs: useId(), hint: useId() };
  const [draft, setDraft] = useState<Draft | null>(null);
  // The list the last successful save answered. "Saved" shows only while the stored list is that one: if
  // the re-read after a 200 failed, the stored list is still the old one and nothing is said (the safe
  // side, a limit of the existing hook).
  const [savedKey, setSavedKey] = useState<string | null>(null);
  const save = useReplaceAllowedPairs(strategy.id);
  const catalogue = useAvailablePairs({
    exchange: strategy.exchange,
    venue: strategy.venue,
    settlement_currency: strategy.settlement_currency,
  });
  // `data` first: a failed background refresh must not hide a list that is already known.
  const status: PairSelectorStatus = catalogue.data !== undefined ? "ready" : catalogue.isError ? "error" : "loading";

  const archived = strategy.archived_at !== null;
  const pairs = draft !== null && draft.base === storedKey(strategy) ? draft.pairs : strategy.allowed_pairs;
  const changed = pairs.join(",") !== storedKey(strategy);
  const empty = pairs.length === 0;

  const handleSave = () => {
    if (!changed || empty || archived) return;
    setSavedKey(null);
    save.mutate(pairs, { onSuccess: (answer) => setSavedKey(savedKeyOf(answer)) });
  };
  // Once the stored list is the saved one, an earlier draft is stale (its base differs) and is not shown,
  // and any later edit clears `savedKey`: so the list on screen is the saved one whenever this is true.
  const saved = savedKey !== null && savedKey === storedKey(strategy);

  const message = save.status === "error" ? saveError(save.error) : null;

  return (
    <section className="flex flex-col gap-3">
      <PairSelector
        id={ids.pairs}
        label={t("strategies.detail.pairs.title")}
        value={pairs}
        onChange={(next) => {
          // A pair added or removed ends "Saved"; typing in the search box never reaches this handler.
          setSavedKey(null);
          setDraft({ base: storedKey(strategy), pairs: next });
        }}
        options={catalogue.data?.pairs}
        status={status}
        onRetry={() => void catalogue.refetch()}
        describedBy={ids.hint}
        disabled={archived}
      />
      <p id={ids.hint} className="text-xs text-ink-3">
        {t("strategies.detail.pairs.hint")}
      </p>
      {empty && !archived && <p className="text-xs text-loss">{t("strategies.detail.pairs.lastPair")}</p>}
      {message !== null && (
        <p role="alert" className="text-sm text-loss">
          {t(message.key, message.values ?? {})}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <button
          type="button"
          onClick={handleSave}
          disabled={archived || !changed || empty || save.isPending}
          className="min-h-11 rounded-md bg-gain px-3 text-sm font-medium text-ground hover:opacity-90 disabled:opacity-50"
        >
          {save.isPending ? t("strategies.detail.pairs.saving") : t("strategies.detail.pairs.save")}
        </button>
        <InlineStatus message={saved ? t("strategies.detail.saved") : null} />
      </div>
    </section>
  );
}
