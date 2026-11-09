import { KeyRound } from "lucide-react";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { entryRefusal } from "@/features/strategies/entry-refusal";
import { useLookUpInviteCode } from "@/shared/api/public-strategies";

const KEY = "strategies.entry";
/** The API reads no longer code (`CODE_MAX_LENGTH`). */
const CODE_MAX_LENGTH = 32;

interface CodeDialogProps {
  onClose: () => void;
}

/**
 * The code, asked in a dialog built like New strategy's: the reader types an invitation code, the API names the
 * strategy it opens, and the strategy's page opens with the code in its address, so its record is read before
 * subscribing. Nothing is spent here. A code that opens nothing says why, in words, and the code stays typed.
 */
function CodeDialog({ onClose }: CodeDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const fieldId = useId();
  const hintId = useId();
  const navigate = useNavigate();
  const lookup = useLookUpInviteCode();
  const [code, setCode] = useState("");
  const typed = code.trim();

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
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onKeyDown={(event) => {
        if (event.key === "Escape" && !lookup.isPending) onClose();
      }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-ground/80 p-4"
    >
      <form
        onSubmit={send}
        noValidate
        className="flex max-h-full w-full max-w-lg flex-col gap-4 overflow-auto rounded-lg border border-rule bg-panel p-6"
      >
        <h2 id={titleId} className="text-sm font-semibold text-ink">
          {t(`${KEY}.haveCode`)}
        </h2>
        <div className="flex flex-col gap-1">
          <label htmlFor={fieldId} className="text-xs font-semibold text-ink-2">
            {t(`${KEY}.codeLabel`)}
          </label>
          <input
            id={fieldId}
            value={code}
            onChange={(event) => setCode(event.target.value)}
            maxLength={CODE_MAX_LENGTH}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            autoFocus
            aria-describedby={hintId}
            className="min-h-11 min-w-0 rounded-md border border-rule bg-ground px-3 font-mono text-sm tracking-wider text-ink"
          />
          <p id={hintId} className="text-xs text-ink-3">
            {t(`${KEY}.codeHint`)}
          </p>
        </div>
        {lookup.isError && (
          <p role="alert" className="text-sm text-loss">
            {t(entryRefusal(lookup.error, { code: typed }) ?? `${KEY}.lookupFailed`)}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={lookup.isPending}
            className="inline-flex min-h-11 items-center rounded-md border border-rule px-3.5 text-sm text-ink-2 hover:bg-panel-2 disabled:opacity-50"
          >
            {t(`${KEY}.cancel`)}
          </button>
          <button
            type="submit"
            disabled={typed === "" || lookup.isPending}
            className="inline-flex min-h-11 items-center rounded-md bg-gain px-3.5 text-sm font-medium text-ground hover:opacity-90 disabled:opacity-50"
          >
            {t(`${KEY}.open`)}
          </button>
        </div>
      </form>
    </div>
  );
}

/**
 * "I have a code", on Explore (decision 41): a button where My strategies puts New strategy, green with its icon,
 * opening a dialog that asks for the code. It sits above the list whatever the list's state, since a strategy
 * shared by a code is on no list.
 */
export function CodeEntry() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  return (
    <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2">
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex min-h-11 items-center gap-1.5 rounded-md bg-gain px-4 text-sm font-medium text-ground hover:opacity-90 disabled:opacity-50"
      >
        <KeyRound aria-hidden="true" className="size-4 shrink-0" />
        {t(`${KEY}.haveCode`)}
      </button>
      {open && <CodeDialog onClose={() => setOpen(false)} />}
    </div>
  );
}
