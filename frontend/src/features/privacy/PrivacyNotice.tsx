import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation } from "react-router";

/** Where the version of the policy a reader dismissed is kept, per browser. */
export const PRIVACY_NOTICE_KEY = "privacy-notice-seen";
/** Changed whenever the policy changes, so the notice comes back (its "Changes" section). */
export const PRIVACY_VERSION = "2026-11-12-draft-2";

function seenThisVersion(): boolean {
  try {
    return window.localStorage.getItem(PRIVACY_NOTICE_KEY) === PRIVACY_VERSION;
  } catch {
    // A browser that refuses storage sees the notice on every visit, never an error.
    return false;
  }
}

/**
 * Tells a reader what the app stores and links the policy, until they dismiss
 * this version of it (Ley 25.326 art. 6: inform when the data is collected,
 * which here is the first sign-in). Dismissing is a convenience kept in the
 * browser, not a record of consent. Opening the policy itself counts as
 * reading it: the notice closes there, for this version.
 */
export function PrivacyNotice() {
  const { t } = useTranslation();
  const onPolicy = useLocation().pathname === "/privacy";
  const [open, setOpen] = useState(() => !seenThisVersion());

  const dismiss = () => {
    try {
      window.localStorage.setItem(PRIVACY_NOTICE_KEY, PRIVACY_VERSION);
    } catch {
      // Not remembered; closed for this page all the same.
    }
    setOpen(false);
  };

  useEffect(() => {
    if (open && onPolicy) dismiss();
  });

  if (!open || onPolicy) return null;

  return (
    <section
      aria-label={t("privacy.notice.label")}
      className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border border-rule bg-panel px-4 py-3 text-sm text-ink-2"
    >
      <p className="min-w-0 flex-1">
        {t("privacy.notice.body")}{" "}
        <Link to="/privacy" className="text-gain hover:text-gain-bright">
          {t("privacy.notice.read")}
        </Link>
      </p>
      <button
        type="button"
        onClick={dismiss}
        className="rounded-md border border-rule px-3 py-1 text-ink hover:border-rule-strong"
      >
        {t("privacy.notice.dismiss")}
      </button>
    </section>
  );
}
