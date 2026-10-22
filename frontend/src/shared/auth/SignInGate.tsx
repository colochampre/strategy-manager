import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/shared/api/client";
import { useMe } from "@/shared/api/me";
import { page } from "@/shared/auth/reauthenticate";

interface SignInGateProps {
  children: ReactNode;
}

/**
 * Shows the panel only to the admin (multi-user design AD1 and AD11).
 *
 * Cloudflare Access has already signed the person in when this renders; the
 * gate asks the API who that is (`GET /api/me`). Until PR B scopes the data by
 * user, every other route is admin-only, so a signed-in user who is not the
 * admin is told so by e-mail instead of meeting a page of refusals.
 *
 * Every state that is not a confirmed admin keeps the children out:
 * - checking: a neutral line;
 * - 503: the API cannot check sign-in right now (Access's keys unreachable); retry;
 * - any other failure: the session could not be renewed (`apiFetch` already
 *   reloaded once); a button loads the page again, through Access's sign-in.
 */
export function SignInGate({ children }: SignInGateProps) {
  const { t } = useTranslation();
  const me = useMe();

  if (me.data?.isAdmin === true) {
    return children;
  }

  let body: ReactNode;
  if (me.data !== undefined) {
    body = <p className="text-sm text-ink">{t("auth.gate.notOpen", { email: me.data.email })}</p>;
  } else if (me.isError && me.error instanceof ApiError && me.error.status === 503) {
    body = (
      <>
        <p className="text-sm text-ink">{t("auth.gate.unavailable")}</p>
        <GateButton onClick={() => void me.refetch()}>{t("auth.gate.retry")}</GateButton>
      </>
    );
  } else if (me.isError) {
    body = (
      <>
        <p className="text-sm text-ink">{t("auth.gate.signedOut")}</p>
        <GateButton onClick={() => page.reload()}>{t("auth.gate.signInAgain")}</GateButton>
      </>
    );
  } else {
    body = (
      <p role="status" className="text-sm text-ink-3">
        {t("auth.gate.checking")}
      </p>
    );
  }

  return (
    <div className="flex flex-1 items-center justify-center">
      <div className="flex w-full max-w-sm flex-col gap-3 rounded-lg border border-rule bg-panel p-6">{body}</div>
    </div>
  );
}

function GateButton({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-md bg-gain px-3 py-2 text-sm font-medium text-ground hover:opacity-90"
    >
      {children}
    </button>
  );
}
