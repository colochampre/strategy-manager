import { type Ref, useEffect, useId, useRef } from "react";
import { Plus, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { exchangeName } from "@/shared/exchanges/exchange-name";

export interface NewKeyControlProps {
  /** The served exchanges with no card, in the file's order: what the select offers. */
  available: readonly string[];
  /** Whether the select is shown instead of the button. */
  open: boolean;
  /** The exchange chosen in the select, or `null` while the placeholder is. */
  chosen: string | null;
  /** A save is in flight somewhere on the page: the button, the select and Cancel are disabled. */
  busy: boolean;
  onOpen: () => void;
  onChoose: (exchange: string) => void;
  onCancel: () => void;
  /** Receives the button, so the page can give it the focus when a card it held the focus on is gone. */
  buttonRef?: Ref<HTMLButtonElement>;
}

/**
 * `New key` and its select (owner decision 80). The button opens a select of the exchanges that can still get a key;
 * the page draws the chosen one's card, with its form open, under this control. With nothing left to offer, there
 * is no button.
 */
export function NewKeyControl({
  available,
  open,
  chosen,
  busy,
  onOpen,
  onChoose,
  onCancel,
  buttonRef,
}: NewKeyControlProps) {
  const { t, i18n } = useTranslation();
  const selectId = useId();
  const select = useRef<HTMLSelectElement>(null);

  // Opening puts the focus on the select, the one thing to do next.
  useEffect(() => {
    if (open) select.current?.focus();
  }, [open]);

  if (available.length === 0) return null;

  if (!open) {
    return (
      <div>
        <button
          ref={buttonRef}
          type="button"
          disabled={busy}
          onClick={onOpen}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-md border border-gain bg-gain px-3.5 text-sm font-medium text-ground disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain"
        >
          <Plus aria-hidden="true" className="size-4 shrink-0" />
          {t("settings.keys.newKey")}
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <label htmlFor={selectId} className="text-sm text-ink-2">
        {t("settings.keys.exchange")}
      </label>
      <select
        ref={select}
        id={selectId}
        value={chosen ?? ""}
        disabled={busy}
        onChange={(event) => {
          if (event.target.value !== "") onChoose(event.target.value);
        }}
        className="min-h-11 rounded-md border border-rule bg-ground px-3 text-sm text-ink disabled:opacity-50"
      >
        <option value="" disabled>
          {t("settings.keys.choose")}
        </option>
        {available.map((exchange) => (
          <option key={exchange} value={exchange}>
            {exchangeName(t, i18n, exchange)}
          </option>
        ))}
      </select>
      <button
        type="button"
        disabled={busy}
        onClick={onCancel}
        className="inline-flex min-h-11 items-center gap-1.5 rounded-md border border-rule px-3.5 text-sm text-ink-2 hover:bg-panel-2 disabled:opacity-50"
      >
        <X aria-hidden="true" className="size-4 shrink-0" />
        {t("settings.keys.cancel")}
      </button>
    </div>
  );
}
