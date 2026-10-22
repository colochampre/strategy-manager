import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { ShieldCheck, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { type SaveRefusal, type SaveResult, saveCredential } from "@/shared/api/credentials";
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
  "inline-flex min-h-11 items-center gap-1.5 rounded-md border border-rule px-3.5 text-sm text-ink-2 hover:bg-panel-2 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-gain";

/**
 * The key form, inside its card (design § F). The two fields are UNCONTROLLED:
 * what the owner types lives in those two DOM elements and nowhere else, not in
 * state, not in a ref's copy, not in a store. Component state holds only whether
 * each field has text, which boxes are ticked, whether a request is in flight and
 * the last refusal as `{reason, missing, status}`.
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
  const [refusal, setRefusal] = useState<{ reason: SaveRefusal; missing: readonly string[]; status: number } | null>(null);
  const mounted = useRef(true);
  const queryClient = useQueryClient();

  useEffect(() => {
    mounted.current = true;
    keyRef.current?.focus();
    return () => {
      mounted.current = false;
    };
  }, []);

  const allTicked = confirmations.every((confirmation) => ticked.includes(confirmation));
  const canSubmit = hasText.key && hasText.secret && allTicked && !checking;

  /**
   * One attempt, step by step (design § F). A ref marks it in flight, because the
   * disabled attribute stops a click and not an Enter. The two strings exist only
   * in the locals below, which go to `saveCredential` and nowhere else. `finally`
   * empties BOTH elements whatever happened, also when the form has left the
   * document (the elements are held by this closure), unticks the boxes and
   * clears the two flags. Every ending but a 401 reads the two lists again, and
   * only a form that is still mounted shows the result; a 401 does nothing, the
   * page is being loaded again to sign in (`apiFetch`).
   */
  async function attempt() {
    if (inFlight.current) return;
    const keyField = keyRef.current;
    const secretField = secretRef.current;
    if (keyField === null || secretField === null) return;
    const apiKey = keyField.value.trim();
    const apiSecret = secretField.value.trim();
    if (apiKey === "" || apiSecret === "" || !allTicked) return;
    inFlight.current = true;
    setRefusal(null);
    setChecking(true);
    onBusyChange(true);
    let result: SaveResult | null = null;
    try {
      result = await saveCredential(exchange, apiKey, apiSecret, confirmations);
    } finally {
      keyField.value = "";
      secretField.value = "";
      inFlight.current = false;
      setHasText({ key: false, secret: false });
      setTicked([]);
      setChecking(false);
      onBusyChange(false);
    }
    if (result === null || result.kind === "unauthorized") return;
    // Also for a form that has left the document: the owner may have gone to another
    // page during the check, and its exchange tabs read the keys before the save ended.
    void queryClient.refetchQueries({ queryKey: ["credentials"] });
    void queryClient.refetchQueries({ queryKey: ["pools"] });
    if (!mounted.current) return;
    if (result.kind === "saved") {
      onSaved({ last4: result.last4, readOnly: result.readOnly });
      return;
    }
    setRefusal({ reason: result.reason, missing: result.missing, status: result.status });
    keyField.focus();
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

  /**
   * The names of a CONFIRMATION_REQUIRED refusal, when the server named only
   * confirmations this form asks for: one line each, with the checkbox's own
   * label. Anything else is said without a list, because a name the panel does
   * not know has no label to show.
   */
  function listedConfirmations(shown: { reason: SaveRefusal; missing: readonly string[] }): readonly string[] {
    if (shown.reason !== "confirmationRequired") return [];
    const known = shown.missing.length > 0 && shown.missing.every((missing) => confirmations.includes(missing));
    return known ? shown.missing : [];
  }

  /** The text is chosen here by `reason`; the server's own wording never reaches the screen. */
  function refusalText(shown: { reason: SaveRefusal; missing: readonly string[]; status: number }): string {
    const reason =
      shown.reason === "confirmationRequired" && listedConfirmations(shown).length === 0
        ? "confirmationRequiredUnlisted"
        : shown.reason;
    return t(`settings.form.error.${reason}`, { exchange: name, status: shown.status });
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

        {refusal !== null && (
          <div role="alert" className="flex max-w-[78ch] flex-col gap-1 text-sm text-loss">
            <p>{refusalText(refusal)}</p>
            {listedConfirmations(refusal).length > 0 && (
              <ul className="list-disc pl-5 text-[13px]">
                {listedConfirmations(refusal).map((confirmation) => (
                  <li key={confirmation}>{t(`settings.form.confirm.${confirmation}`, { exchange: name })}</li>
                ))}
              </ul>
            )}
            <p className="text-[13px] text-ink-3">{t("settings.form.emptied")}</p>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <StatusButton
            texts={[t("settings.form.submit"), t("settings.form.submitting")]}
            shown={checking ? t("settings.form.submitting") : t("settings.form.submit")}
            message={null}
            submit
            disabled={!canSubmit}
            icon={ShieldCheck}
            className={SUBMIT}
          />
          <button type="button" onClick={onClose} disabled={checking} className={CLOSE}>
            <X aria-hidden="true" className="size-4 shrink-0" />
            {t("settings.form.close")}
          </button>
        </div>
      </form>
    </section>
  );
}
