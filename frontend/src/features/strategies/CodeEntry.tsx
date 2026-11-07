import { KeyRound } from "lucide-react";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { entryRefusal } from "@/features/strategies/entry-refusal";
import { useLookUpInviteCode } from "@/shared/api/public-strategies";

const KEY = "strategies.entry";
/** The API reads no longer code (`CODE_MAX_LENGTH`). */
const CODE_MAX_LENGTH = 32;

/**
 * "I have a code", on Explore (decision 41): the reader types an invitation code, the API names the strategy it
 * opens, and the strategy's page opens with the code in its address, so its record is read before subscribing.
 * Nothing is spent here. A code that opens nothing says why, in words, and the code stays typed.
 */
export function CodeEntry() {
  const { t } = useTranslation();
  const fieldId = useId();
  const hintId = useId();
  const navigate = useNavigate();
  const lookup = useLookUpInviteCode();
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const typed = code.trim();

  if (!open) {
    return (
      <div>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex min-h-11 items-center gap-2 rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2"
        >
          <KeyRound aria-hidden="true" className="size-4" />
          {t(`${KEY}.haveCode`)}
        </button>
      </div>
    );
  }

  const send = (event: FormEvent) => {
    event.preventDefault();
    if (typed === "" || lookup.isPending) return;
    lookup.mutate(typed, {
      onSuccess: (strategyId) => {
        void navigate(`/strategies/explore/${encodeURIComponent(strategyId)}?code=${encodeURIComponent(typed)}`);
      },
    });
  };

  return (
    <form onSubmit={send} className="flex flex-col gap-2 rounded-md border border-rule bg-panel px-4 py-3">
      <label htmlFor={fieldId} className="text-xs font-semibold text-ink-2">
        {t(`${KEY}.codeLabel`)}
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <input
          id={fieldId}
          value={code}
          onChange={(event) => setCode(event.target.value)}
          maxLength={CODE_MAX_LENGTH}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          aria-describedby={hintId}
          className="min-h-11 min-w-0 grow rounded-md border border-rule bg-ground px-3 font-mono text-sm tracking-wider text-ink"
        />
        <button
          type="submit"
          disabled={typed === "" || lookup.isPending}
          className="inline-flex min-h-11 items-center rounded-md bg-gain px-3.5 text-sm font-medium text-ground hover:opacity-90 disabled:opacity-50"
        >
          {t(`${KEY}.open`)}
        </button>
      </div>
      <p id={hintId} className="text-xs text-ink-3">
        {t(`${KEY}.codeHint`)}
      </p>
      {lookup.isError && (
        <p role="alert" className="text-sm text-loss">
          {t(entryRefusal(lookup.error, { code: typed }) ?? `${KEY}.lookupFailed`)}
        </p>
      )}
    </form>
  );
}
