import { useTranslation } from "react-i18next";
import { Link, Outlet } from "react-router";

import { ProfileGate } from "@/features/sign-up/ProfileGate";
import { useSignUpPending } from "@/shared/api/me";

import { SignInGate } from "@/shared/auth/SignInGate";
import { BottomNav } from "@/shared/layout/BottomNav";
import { SideNav } from "@/shared/layout/SideNav";
import { TopBar } from "@/shared/layout/TopBar";

/**
 * The page frame. It is exactly one viewport tall (`#root` is 100% high), a
 * flex column of top bar, body and (on phones) bottom bar, and only `main`
 * scrolls. `min-h-0` on the flex children lets them shrink below their
 * content so the scroll happens inside `main` instead of on the page.
 *
 * The sign-in gate sits inside `main`, so the badge and navigation stay visible
 * while it checks who is signed in (`/health` is outside Access's check in the
 * API) and the gate card fills the space `main` leaves over.
 *
 * `main` stays full width, so its scrollbar sits at the window edge. Every page
 * lives in one centred column capped at 90rem (decision 38), so a very wide
 * screen adds margin around the content instead of stretching it, and the
 * space between the pool panel and the decision rail never grows.
 *
 * `main` is `relative`: it is the scroll container, so it must also be the
 * containing block of anything `position: absolute` inside it (the `sr-only`
 * spans of the tables). Unpositioned, those are laid out against the document,
 * far below, and stretch its height into a second scrollbar over empty space.
 *
 * That column deliberately has NO `min-h-0`: it must be as tall as its content.
 * Capped at the space `main` leaves, a long page overflowed the column, so the
 * padding of `main` sat under the capped column and not under the last row, and
 * the row ended flush with the bottom of the viewport. Uncapped, `main` scrolls
 * the whole column and its bottom padding follows the content (task 7p.3). A
 * short page still fills `main`, because the column is `flex-1`.
 *
 * Every page ends with links to the privacy policy and the terms. The footer sits
 * inside the gate: whoever reaches it has signed in.
 *
 * Inside it, the sign-up step (public-site LS2) takes the page's place until the
 * user has given their details and accepted the terms in force. That form is
 * where the user is informed (Ley 25.326 art. 6): it links the policy and records
 * the version accepted, and asks again when it changes. The footer stays,
 * so the terms and the policy the form asks to accept are one click away. The
 * navigation (and, in the top bar, the exchange tabs and the mode badge) waits
 * for it too: nothing of the panel to go to or act on. While `me` loads it
 * shows, as before sign-up existed.
 */
export function AppShell() {
  const { t } = useTranslation();
  const signUpPending = useSignUpPending();

  return (
    <div className="flex h-full flex-col bg-ground">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        {!signUpPending && <SideNav />}
        <main className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-auto p-4 lg:px-9 lg:py-7">
          <div className="mx-auto flex w-full max-w-[90rem] flex-1 flex-col">
            <SignInGate>
              <ProfileGate>
                <Outlet />
              </ProfileGate>
              <div className="mt-auto pt-10">
                <footer className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-rule pt-5 text-xs text-ink-3">
                  <span>{t("privacy.copyright", { year: new Date().getFullYear() })}</span>
                  <Link to="/privacy" className="text-ink-2 hover:text-ink">
                    {t("privacy.link")}
                  </Link>
                  <Link to="/terms" className="text-ink-2 hover:text-ink">
                    {t("terms.link")}
                  </Link>
                </footer>
              </div>
            </SignInGate>
          </div>
        </main>
      </div>
      {!signUpPending && <BottomNav />}
    </div>
  );
}
