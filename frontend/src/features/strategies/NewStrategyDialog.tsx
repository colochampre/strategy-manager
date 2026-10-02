import { useId, useState } from "react";
import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/shared/api/client";
import { useRegisterStrategy } from "@/shared/api/strategies";
import type { FillMode, Pool } from "@/shared/api/types";

const FILL_MODES: readonly FillMode[] = ["SKIP", "PARTIAL"];

/** The server's default for a new strategy: it may use all the capital that is available. */
const ALLOCATION_PERCENT = "100";

interface NewStrategyDialogProps {
  /** The selected exchange: a strategy is registered on one of its pools. */
  exchange: string;
  /** The pools of that exchange the strategy may be registered on (enabled ones). */
  pools: readonly Pool[];
  onClose: () => void;
}

/** One pair per line or separated by commas; trimmed, empties dropped, first spelling of a duplicate kept. */
function parsePairs(text: string): string[] {
  const seen = new Set<string>();
  for (const part of text.split(/[\n,]/)) {
    const pair = part.trim();
    if (pair !== "") seen.add(pair);
  }
  return [...seen];
}

function poolValue(pool: Pool): string {
  return `${pool.venue}/${pool.settlement_currency}`;
}

function errorKey(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) return "strategies.new.errors.conflict";
  if (error instanceof ApiError && error.status === 422) return "strategies.new.errors.invalid";
  return "strategies.new.errors.generic";
}

/**
 * Registers a strategy. The id is the alert's `signalType` and is generated
 * here, once per opening, with `crypto.randomUUID()`: the server has no default
 * because one it made up would match no alert, and a retry after a failure
 * reuses the same id so it cannot register twice. At least one allowed pair is
 * required (decision 13). A new strategy starts disabled; arming it is the
 * list's switch, a separate act.
 *
 * The exchange, venue and currency come from a pool and cannot change later,
 * and the fill mode has no default: it decides what a signal does when capital
 * is short, so the operator picks it.
 */
export function NewStrategyDialog({ exchange, pools, onClose }: NewStrategyDialogProps) {
  const { t } = useTranslation();
  const ids = { title: useId(), name: useId(), pool: useId(), fillMode: useId(), pairs: useId(), hint: useId() };
  const [strategyId] = useState(() => crypto.randomUUID());
  const [name, setName] = useState("");
  const [selectedPool, setSelectedPool] = useState("");
  const [fillMode, setFillMode] = useState("");
  const [pairsText, setPairsText] = useState("");
  const [validation, setValidation] = useState<string | null>(null);
  const register = useRegisterStrategy();

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const pool = pools.find((candidate) => poolValue(candidate) === selectedPool);
    if (name.trim() === "" || pool === undefined || !FILL_MODES.includes(fillMode as FillMode)) {
      setValidation("strategies.new.incomplete");
      return;
    }
    const pairs = parsePairs(pairsText);
    if (pairs.length === 0) {
      setValidation("strategies.new.pairsRequired");
      return;
    }
    setValidation(null);
    register.mutate(
      {
        id: strategyId,
        name: name.trim(),
        exchange,
        venue: pool.venue,
        settlement_currency: pool.settlement_currency,
        fill_mode: fillMode as FillMode,
        allocation_percent: ALLOCATION_PERCENT,
        allowed_pairs: pairs,
      },
      { onSuccess: onClose },
    );
  };

  const messageKey = validation ?? (register.status === "error" ? errorKey(register.error) : null);
  const inputClass = "rounded-md border border-rule bg-ground px-3 py-2 text-sm text-ink";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={ids.title}
      onKeyDown={(event) => {
        if (event.key === "Escape" && !register.isPending) onClose();
      }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-ground/80 p-4"
    >
      <form
        onSubmit={handleSubmit}
        noValidate
        className="flex max-h-full w-full max-w-lg flex-col gap-4 overflow-auto rounded-lg border border-rule bg-panel p-6"
      >
        <h2 id={ids.title} className="text-sm font-semibold text-ink">
          {t("strategies.new.title")}
        </h2>

        <div className="flex flex-col gap-1">
          <label htmlFor={ids.name} className="text-xs font-semibold text-ink-2">
            {t("strategies.new.name")}
          </label>
          <input
            id={ids.name}
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoComplete="off"
            className={inputClass}
          />
        </div>

        {pools.length === 0 ? (
          <p role="status" className="text-sm text-ink-3">
            {t("strategies.new.noPools")}
          </p>
        ) : (
          <div className="flex flex-col gap-1">
            <label htmlFor={ids.pool} className="text-xs font-semibold text-ink-2">
              {t("strategies.new.pool")}
            </label>
            <select
              id={ids.pool}
              value={selectedPool}
              onChange={(event) => setSelectedPool(event.target.value)}
              className={inputClass}
            >
              <option value="">{t("strategies.new.poolPlaceholder")}</option>
              {pools.map((pool) => (
                <option key={poolValue(pool)} value={poolValue(pool)}>
                  {`${pool.exchange} · ${pool.venue} · ${pool.settlement_currency}`}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="flex flex-col gap-1">
          <label htmlFor={ids.fillMode} className="text-xs font-semibold text-ink-2">
            {t("strategies.new.fillMode")}
          </label>
          <select
            id={ids.fillMode}
            value={fillMode}
            onChange={(event) => setFillMode(event.target.value)}
            className={inputClass}
          >
            <option value="">{t("strategies.new.fillModePlaceholder")}</option>
            {FILL_MODES.map((mode) => (
              <option key={mode} value={mode}>
                {t(`strategies.new.fillModes.${mode}`)}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor={ids.pairs} className="text-xs font-semibold text-ink-2">
            {t("strategies.new.pairs")}
          </label>
          <textarea
            id={ids.pairs}
            value={pairsText}
            onChange={(event) => setPairsText(event.target.value)}
            aria-describedby={ids.hint}
            rows={3}
            spellCheck={false}
            className={`${inputClass} font-mono`}
          />
          <p id={ids.hint} className="text-xs text-ink-3">
            {t("strategies.new.pairsHint")}
          </p>
        </div>

        {messageKey !== null && (
          <p role="alert" className="text-sm text-loss">
            {t(messageKey)}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={register.isPending}
            className="rounded-md border border-rule px-3 py-1.5 text-sm text-ink-2 hover:bg-panel-2 disabled:opacity-50"
          >
            {t("strategies.new.cancel")}
          </button>
          <button
            type="submit"
            disabled={register.isPending || pools.length === 0}
            className="rounded-md bg-gain px-3 py-1.5 text-sm font-medium text-ground hover:opacity-90 disabled:opacity-50"
          >
            {register.isPending ? t("strategies.new.submitting") : t("strategies.new.submit")}
          </button>
        </div>
      </form>
    </div>
  );
}
