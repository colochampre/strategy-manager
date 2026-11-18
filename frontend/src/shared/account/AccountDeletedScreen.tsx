import { LogOut } from "lucide-react";
import { useTranslation } from "react-i18next";

/** Cloudflare Access ends its session here; the next visit asks to sign in again. */
export const ACCESS_LOGOUT = "/cdn-cgi/access/logout";

/**
 * What the panel draws once the account is deleted (account-deletion S5), in place of every route. It reads
 * nothing: a request now would sign the same e-mail in again as a new, empty account.
 */
export function AccountDeletedScreen() {
  const { t } = useTranslation();
  return (
    <main className="flex min-h-dvh items-center justify-center bg-ground px-4 text-ink">
      <div className="flex w-full max-w-sm flex-col gap-3 rounded-lg border border-rule bg-panel p-6">
        <h1 className="font-display text-lg font-semibold text-ink">{t("accountDeleted.title")}</h1>
        <p className="text-sm text-ink-2">{t("accountDeleted.body")}</p>
        <a
          href={ACCESS_LOGOUT}
          className="inline-flex min-h-11 items-center justify-center gap-1.5 self-start rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain"
        >
          <LogOut aria-hidden="true" className="size-4 shrink-0" />
          {t("accountDeleted.signOut")}
        </a>
      </div>
    </main>
  );
}
