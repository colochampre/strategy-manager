import { useState } from "react";
import { useTranslation } from "react-i18next";

export type PairSelectorStatus = "idle" | "loading" | "error" | "ready";

export interface PairSelectorProps {
  /** Id of the fieldset; the search field derives its own from it. */
  id: string;
  /** The group's visible name (the legend). */
  label: string;
  /** The selected pairs, in market-key form (`STXUSDT`). */
  value: readonly string[];
  onChange: (next: string[]) => void;
  /** The pool's available pairs, in market-key form; `undefined` until they are read. */
  options: readonly string[] | undefined;
  status: PairSelectorStatus;
  onRetry: () => void;
  describedBy?: string;
  disabled?: boolean;
}

/** How many matches are rendered; the count line says how many there are. */
const MAX_RENDERED = 50;

/** The TradingView and Pionex spellings of a market, which the typed text may carry. */
const SPELLING_SUFFIX = /(\.P|_PERP)$/;

/**
 * A display filter only (the server decides what is valid): the typed text,
 * upper-cased and without a `.P` or `_PERP` suffix, so pasting `STXUSDT.P`
 * finds `STXUSDT`.
 */
function searchTerm(typed: string): string {
  return typed.trim().toUpperCase().replace(SPELLING_SUFFIX, "");
}

/**
 * Chooses allowed pairs from the pool's available pairs. Controlled and
 * presentational: the options, the selection and the load state come in as
 * props and the query lives outside it. Native elements only (a fieldset, a
 * search input, checkboxes, buttons), so the keyboard works without any
 * handler of its own.
 *
 * A selected pair that is not among the options (`ready` only, when the list
 * is known) stays in the selection as a "no longer listed" chip until the
 * operator removes it: dropping it silently would turn the next save into an
 * unintended removal. Selected pairs are removable in every state.
 */
export function PairSelector({
  id,
  label,
  value,
  onChange,
  options,
  status,
  onRetry,
  describedBy,
  disabled,
}: PairSelectorProps) {
  const { t } = useTranslation();
  const [typed, setTyped] = useState("");
  const searchId = `${id}-search`;
  const ready = status === "ready" && options !== undefined;

  const term = searchTerm(typed);
  const matches = ready ? options.filter((pair) => pair.toUpperCase().includes(term)) : [];
  const shown = matches.slice(0, MAX_RENDERED);
  const listed = new Set(options);
  const selected = new Set(value);

  const toggle = (pair: string) => {
    onChange(selected.has(pair) ? value.filter((chosen) => chosen !== pair) : [...value, pair]);
  };

  return (
    <fieldset id={id} disabled={disabled} aria-describedby={describedBy} className="flex min-w-0 flex-col gap-2">
      <legend className="text-xs font-semibold text-ink-2">{label}</legend>

      {value.length > 0 && (
        <ul aria-label={t("strategies.pairs.selected")} className="flex flex-wrap gap-1">
          {value.map((pair) => (
            <li
              key={pair}
              className="inline-flex items-center gap-1 rounded-full border border-rule bg-panel-2 py-0.5 pl-3 pr-1 text-xs text-ink"
            >
              <span className="font-mono">{pair}</span>
              {ready && !listed.has(pair) && <span className="text-ink-3">{t("strategies.pairs.notListed")}</span>}
              <button
                type="button"
                aria-label={t("strategies.pairs.remove", { symbol: pair })}
                onClick={() => onChange(value.filter((chosen) => chosen !== pair))}
                className="rounded-full px-2 text-ink-3 hover:text-ink"
              >
                <span aria-hidden="true">×</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <label htmlFor={searchId} className="text-xs text-ink-2">
        {t("strategies.pairs.search")}
      </label>
      <input
        id={searchId}
        type="search"
        value={typed}
        onChange={(event) => setTyped(event.target.value)}
        // Enter in a search field would submit an enclosing form (the new-strategy dialog).
        onKeyDown={(event) => {
          if (event.key === "Enter") event.preventDefault();
        }}
        disabled={!ready}
        autoComplete="off"
        spellCheck={false}
        className="rounded-md border border-rule bg-ground px-3 py-2 font-mono text-sm text-ink disabled:opacity-50"
      />

      {status === "idle" && <p className="text-sm text-ink-3">{t("strategies.pairs.choosePool")}</p>}

      {status === "loading" && (
        <p role="status" className="text-sm text-ink-3">
          {t("strategies.pairs.loading")}
        </p>
      )}

      {status === "error" && (
        <div className="flex flex-wrap items-center gap-2">
          <p role="alert" className="text-sm text-loss">
            {t("strategies.pairs.loadFailed")}
          </p>
          <button
            type="button"
            onClick={onRetry}
            className="rounded-md border border-rule px-3 py-1 text-sm text-ink-2 hover:bg-panel-2"
          >
            {t("strategies.pairs.retry")}
          </button>
        </div>
      )}

      {ready && (
        <>
          <div aria-live="polite" className="text-xs text-ink-3">
            {matches.length === 0 ? (
              <p>{t("strategies.pairs.noMatch")}</p>
            ) : (
              <p>{t("strategies.pairs.showing", { shown: shown.length, total: matches.length })}</p>
            )}
            {matches.length > shown.length && <p>{t("strategies.pairs.narrow")}</p>}
          </div>
          {shown.length > 0 && (
            <ul className="max-h-60 overflow-auto rounded-md border border-rule bg-ground p-1">
              {shown.map((pair) => (
                <li key={pair}>
                  <label className="flex items-center gap-2 rounded px-2 py-1 text-sm text-ink hover:bg-panel-2">
                    <input
                      type="checkbox"
                      checked={selected.has(pair)}
                      onChange={() => toggle(pair)}
                      className="accent-gain"
                    />
                    <span className="font-mono">{pair}</span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </fieldset>
  );
}
