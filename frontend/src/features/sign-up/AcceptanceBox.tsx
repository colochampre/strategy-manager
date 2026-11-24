import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { LegalVersions } from "@/shared/api/me";

/**
 * The acceptance as the versions it was ticked under, not a bare boolean. `me` is read again every minute and on focus,
 * so the versions a form shows can change under a ticked box; a tick given under other versions is no tick at all
 * (LS6), and the box reads unticked until it is ticked again under the versions now shown.
 */
export function useAcceptance(versions: LegalVersions) {
  const [tickedUnder, setTickedUnder] = useState<LegalVersions | null>(null);
  const current =
    tickedUnder !== null && tickedUnder.terms === versions.terms && tickedUnder.privacy === versions.privacy;
  return {
    ticked: current,
    /** Ticked under versions no longer in force: the form says so. */
    outdated: tickedUnder !== null && !current,
    set: (checked: boolean) => setTickedUnder(checked ? versions : null),
    clear: () => setTickedUnder(null),
  };
}

const LINK = "text-gain underline hover:text-gain-bright";

interface AcceptanceBoxProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
}

/**
 * "I accept the terms and have read the privacy policy", with the express consent to the transfer abroad written in
 * (LS2's last box). Both documents open in a new tab, so whatever the form holds stays as typed.
 */
export function AcceptanceBox({ checked, onChange }: AcceptanceBoxProps) {
  const { t } = useTranslation();
  const id = useId();
  return (
    <div className="flex items-start gap-3 text-sm text-ink-2">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 size-4 shrink-0 accent-gain"
      />
      <label htmlFor={id}>
        {t("signUp.acceptsBefore")}
        <a href="/terms" target="_blank" rel="noopener noreferrer" className={LINK}>
          {t("signUp.termsLink")}
        </a>
        {t("signUp.acceptsMiddle")}
        <a href="/privacy" target="_blank" rel="noopener noreferrer" className={LINK}>
          {t("signUp.privacyLink")}
        </a>
        {t("signUp.acceptsAfter")}
      </label>
    </div>
  );
}

export function SubmitButton({ disabled, busy }: { disabled: boolean; busy: boolean }) {
  const { t } = useTranslation();
  return (
    <button
      type="submit"
      disabled={disabled}
      aria-busy={busy}
      className="self-start rounded-lg bg-gain px-4 py-2 text-sm font-medium text-ground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {t("signUp.submit")}
    </button>
  );
}
