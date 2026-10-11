import { useRef, useState } from "react";
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

/**
 * RED STUB (task 13.5.1). The fields are CONTROLLED and the `finally` empties
 * only the secret, so the tests of design § H rows 4 and 12 fail on their
 * assertions. It re-reads nothing and moves no focus.
 */
export function KeyEntryForm({ id, exchange, name, onClose, onSaved, onBusyChange }: KeyEntryFormProps) {
  const { t } = useTranslation();
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [checking, setChecking] = useState(false);
  const inFlight = useRef(false);

  async function attempt() {
    if (inFlight.current) return;
    if (apiKey.trim() === "" || apiSecret.trim() === "") return;
    inFlight.current = true;
    setChecking(true);
    onBusyChange(true);
    try {
      const result = await saveCredential(exchange, apiKey.trim(), apiSecret.trim(), []);
      if (result.kind === "saved") onSaved({ last4: result.last4, readOnly: result.readOnly });
    } finally {
      setApiSecret("");
      inFlight.current = false;
      setChecking(false);
      onBusyChange(false);
    }
  }

  return (
    <section id={id} aria-label={t("settings.form.addTitle", { exchange: name })}>
      <h4>{t("settings.form.addTitle", { exchange: name })}</h4>
      <label>
        {t("settings.form.apiKey")}
        <input type="text" value={apiKey} readOnly={checking} onChange={(event) => setApiKey(event.target.value)} />
      </label>
      <label>
        {t("settings.form.apiSecret")}
        <input
          type="password"
          value={apiSecret}
          readOnly={checking}
          onChange={(event) => setApiSecret(event.target.value)}
        />
      </label>
      <StatusButton
        texts={[t("settings.form.submit"), t("settings.form.submitting")]}
        shown={checking ? t("settings.form.submitting") : t("settings.form.submit")}
        message={null}
        onClick={() => void attempt()}
        disabled={checking || apiKey.trim() === "" || apiSecret.trim() === ""}
        className=""
      />
      <button type="button" onClick={onClose}>
        {t("settings.form.close")}
      </button>
    </section>
  );
}
