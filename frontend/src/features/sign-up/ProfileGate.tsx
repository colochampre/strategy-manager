import type { ReactNode } from "react";
import { useLocation } from "react-router";

import { AcceptAgainForm } from "@/features/sign-up/AcceptAgainForm";
import { SignUpForm } from "@/features/sign-up/SignUpForm";
import { useMe } from "@/shared/api/me";

/** The pages the form links, readable before signing up: nobody accepts what they cannot read. */
const READABLE_BEFORE_SIGN_UP = new Set(["/terms", "/privacy"]);

/**
 * The sign-up step (public-site LS2, LS6). It sits inside `SignInGate`, so who is signed in is already known.
 * - COMPLETE: the panel.
 * - MISSING: the whole form, and nothing else of the panel until it is sent.
 * - ACCEPTANCE_OUTDATED: the acceptance box alone, under the versions in force.
 *
 * The terms and the policy stay readable at every step. The API refuses every write that stores or trades until the
 * profile is complete (LS4), so this screen is not the only guard.
 */
export function ProfileGate({ children }: { children: ReactNode }) {
  const me = useMe();
  const { pathname } = useLocation();

  if (me.data === undefined) return null;
  if (me.data.profileStatus === "COMPLETE" || READABLE_BEFORE_SIGN_UP.has(pathname)) return children;

  return (
    <div className="flex flex-1 items-start justify-center py-6">
      <div className="flex w-full max-w-lg flex-col gap-4 rounded-lg border border-rule bg-panel p-6">
        {me.data.profileStatus === "MISSING" ? (
          <SignUpForm versions={me.data.legalVersions} />
        ) : (
          <AcceptAgainForm versions={me.data.legalVersions} />
        )}
      </div>
    </div>
  );
}
