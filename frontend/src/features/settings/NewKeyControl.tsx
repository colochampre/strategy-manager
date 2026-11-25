import { type Ref, useEffect, useId, useRef } from "react";
import { CirclePlus, X } from "lucide-react";
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
    // The prototype's `.bar-btn` (ex6): across the whole width, 44 px, dashed, on panel-2, the plus in gain.
    return (
      <button
        ref={buttonRef}
        type="button"
        disabled={busy}
        onClick={onOpen}
        className="flex h-11 w-full items-center justify-center gap-2.5 rounded-lg border border-dashed border-rule-strong bg-panel-2 text-sm font-medium text-ink transition-colors hover:border-gain/60 motion-reduce:transition-none disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain"
      >
        <CirclePlus aria-hidden="true" className="size-[18px] shrink-0 text-gain" />
        {t("settings.keys.newKey")}
      </button>
    );
  }

  return (
    <div className="flex w-full items-center gap-2 lg:w-1/2">
      {/* Read by assistive technology only: the select's placeholder already says what to choose (L14). */}
      <label htmlFor={selectId} className="sr-only">
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
        className="h-9 min-w-0 flex-1 rounded-lg border border-rule-strong bg-panel-2 px-3 text-sm text-ink disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain"
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
        className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-rule bg-panel px-3.5 text-sm text-ink-2 transition-colors hover:bg-panel-2 motion-reduce:transition-none disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain"
      >
        <X aria-hidden="true" className="size-4 shrink-0" />
        {t("settings.keys.cancel")}
      </button>
    </div>
  );
}
