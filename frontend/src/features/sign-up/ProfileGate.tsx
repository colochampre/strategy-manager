import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation } from "react-router";

import { AcceptAgainForm } from "@/features/sign-up/AcceptAgainForm";
import { SignUpForm } from "@/features/sign-up/SignUpForm";
import { WAY_OUT_PATH } from "@/features/way-out/WayOutPage";
import { useMe } from "@/shared/api/me";

/**
 * The pages open before signing up: the ones the form links, since nobody accepts what they cannot read, and the
 * way out, since nobody should have to accept terms to close what they hold (public-site PS.15).
 */
const OPEN_BEFORE_SIGN_UP = new Set(["/terms", "/privacy", WAY_OUT_PATH]);

/**
 * The sign-up step (public-site LS2, LS6). It sits inside `SignInGate`, so who is signed in is already known.
 * - COMPLETE: the panel.
 * - MISSING: the whole form, and nothing else of the panel until it is sent.
 * - ACCEPTANCE_OUTDATED: the acceptance box alone, under the versions in force.
 *
 * The terms and the policy stay readable at every step, and under either form a link opens the way out. The API
 * refuses every write that stores or trades until the profile is complete (LS4), so this screen is not the only
 * guard.
 */
export function ProfileGate({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const me = useMe();
  const { pathname } = useLocation();

  if (me.data === undefined) return null;
  if (me.data.profileStatus === "COMPLETE" || OPEN_BEFORE_SIGN_UP.has(pathname)) return children;

  return (
    <div className="flex flex-1 items-start justify-center py-6">
      <div className="flex w-full max-w-lg flex-col gap-4">
        <div className="flex flex-col gap-4 rounded-lg border border-rule bg-panel p-6">
          {me.data.profileStatus === "MISSING" ? (
            <SignUpForm versions={me.data.legalVersions} />
          ) : (
            <AcceptAgainForm versions={me.data.legalVersions} />
          )}
        </div>
        <p className="px-1 text-sm text-ink-2">
          {t("wayOut.linkIntro")}{" "}
          <Link to={WAY_OUT_PATH} className="underline hover:text-ink">
            {t("wayOut.link")}
          </Link>
        </p>
      </div>
    </div>
  );
}
