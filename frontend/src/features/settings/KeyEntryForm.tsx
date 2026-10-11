import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { saveCredential } from "@/shared/api/credentials";
import { StatusButton } from "@/shared/ui/StatusButton";

/** What the form hands the page when a save worked: the answer's four characters (or none) and whether the key cannot trade. */
export interface SavedKey {
  last4: string | null;
  readOnly: boolean;
}

export interface KeyEntryFormProps {
  /** The DOM id of the form's section: the toggle that opens it points at it with `aria-controls`. */
  id: string;
  /** The exchange's id as the API spells it. */
  exchange: string;
  /** The exchange's proper name. */
  name: string;
  /** Whether a key is stored now, so the form says it replaces one. */
  hasKey: boolean;
  /** The confirmations the exchange asks for, by name (from `served-exchanges.json`). */
  confirmations: readonly string[];
  onClose: () => void;
  onSaved: (saved: SavedKey) => void;
  /** Called with `true` when an attempt starts and `false` when it ends, so the page can disable every button. */
  onBusyChange: (busy: boolean) => void;
}

const FIELD =
  "min-h-11 w-full rounded-md border border-rule bg-ground px-3 font-mono text-sm text-ink focus-visible:outline-2 focus-visible:outline-gain";
const LABEL = "text-[13px] text-ink-2";
const HELP = "max-w-[78ch] text-[13px] text-ink-3";
const SUBMIT =
  "min-h-11 rounded-md border border-gain bg-gain px-3.5 text-sm font-medium text-ground disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain";
const CLOSE =
  "min-h-11 rounded-md border border-rule px-3.5 text-sm text-ink-2 hover:bg-panel-2 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-gain";

/**
 * The key form, inside its card (design § F). The two fields are UNCONTROLLED:
 * what the owner types lives in those two DOM elements and nowhere else, not in
 * state, not in a ref's copy, not in a store. Component state holds only whether
 * each field has text, which boxes are ticked, and whether a request is in flight.
 *
 * TASK 13.5.4: the shape. The attempt is still the bare one; task 13.5.6 finishes it.
 */
export function KeyEntryForm({ id, exchange, name, hasKey, confirmations, onClose, onSaved, onBusyChange }: KeyEntryFormProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const keyId = useId();
  const secretId = useId();
  const helpId = useId();
  const keyRef = useRef<HTMLInputElement>(null);
  const secretRef = useRef<HTMLInputElement>(null);
  const inFlight = useRef(false);
  const [hasText, setHasText] = useState({ key: false, secret: false });
  const [ticked, setTicked] = useState<readonly string[]>([]);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    keyRef.current?.focus();
  }, []);

  const allTicked = confirmations.every((confirmation) => ticked.includes(confirmation));
  const canSubmit = hasText.key && hasText.secret && allTicked && !checking;

  async function attempt() {
    if (inFlight.current) return;
    const keyField = keyRef.current;
    const secretField = secretRef.current;
    if (keyField === null || secretField === null) return;
    const apiKey = keyField.value.trim();
    const apiSecret = secretField.value.trim();
    if (apiKey === "" || apiSecret === "" || !allTicked) return;
    inFlight.current = true;
    setChecking(true);
    onBusyChange(true);
    try {
      const result = await saveCredential(exchange, apiKey, apiSecret, confirmations);
      if (result.kind === "saved") onSaved({ last4: result.last4, readOnly: result.readOnly });
    } finally {
      secretField.value = "";
      inFlight.current = false;
      setChecking(false);
      onBusyChange(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void attempt();
  }

  function toggle(confirmation: string) {
    setTicked((current) =>
      current.includes(confirmation) ? current.filter((item) => item !== confirmation) : [...current, confirmation],
    );
  }

  const title = hasKey ? t("settings.form.replaceTitle", { exchange: name }) : t("settings.form.addTitle", { exchange: name });

  return (
    <section
      id={id}
      aria-labelledby={titleId}
      className="flex min-w-0 flex-col gap-3.5 rounded-lg border border-dashed border-rule-strong p-5"
    >
      <h4 id={titleId} className="font-display text-base font-semibold text-ink">
        {title}
      </h4>
      <form noValidate onSubmit={submit} className="flex flex-col gap-3.5">
        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
          <div className="flex min-w-0 flex-col gap-1.5">
            <label htmlFor={keyId} className={LABEL}>
              {t("settings.form.apiKey")}
            </label>
            <input
              ref={keyRef}
              id={keyId}
              type="text"
              autoComplete="off"
              spellCheck={false}
              autoCapitalize="off"
              autoCorrect="off"
              readOnly={checking}
              aria-describedby={helpId}
              onChange={(event) => {
                const filled = event.target.value.trim() !== "";
                setHasText((current) => ({ ...current, key: filled }));
              }}
              className={FIELD}
            />
          </div>
          <div className="flex min-w-0 flex-col gap-1.5">
            <label htmlFor={secretId} className={LABEL}>
              {t("settings.form.apiSecret")}
            </label>
            <input
              ref={secretRef}
              id={secretId}
              type="password"
              autoComplete="new-password"
              readOnly={checking}
              aria-describedby={helpId}
              onChange={(event) => {
                const filled = event.target.value.trim() !== "";
                setHasText((current) => ({ ...current, secret: filled }));
              }}
              className={FIELD}
            />
          </div>
        </div>

        <p id={helpId} className={HELP}>
          {confirmations.length === 0
            ? t("settings.form.helpVerified", { exchange: name })
            : t("settings.form.helpConfirmed", { exchange: name })}
        </p>
        {hasKey && <p className={HELP}>{t("settings.form.replaceNote")}</p>}

        {confirmations.length > 0 && (
          <>
            <fieldset className="flex flex-col gap-1">
              <legend className="pb-1 text-[13px] text-ink-2">{t("settings.form.confirm.legend", { exchange: name })}</legend>
              {confirmations.map((confirmation) => (
                <label key={confirmation} className="flex min-h-11 items-center gap-2.5 text-sm text-ink">
                  <input
                    type="checkbox"
                    checked={ticked.includes(confirmation)}
                    disabled={checking}
                    onChange={() => toggle(confirmation)}
                    className="size-4 accent-gain"
                  />
                  {t(`settings.form.confirm.${confirmation}`, { exchange: name })}
                </label>
              ))}
            </fieldset>
            <p className={HELP}>{t("settings.form.confirm.help", { exchange: name })}</p>
          </>
        )}

        <div className="flex flex-wrap gap-2">
          <StatusButton
            texts={[t("settings.form.submit"), t("settings.form.submitting")]}
            shown={checking ? t("settings.form.submitting") : t("settings.form.submit")}
            message={null}
            submit
            disabled={!canSubmit}
            className={SUBMIT}
          />
          <button type="button" onClick={onClose} className={CLOSE}>
            {t("settings.form.close")}
          </button>
        </div>
      </form>
    </section>
  );
}
