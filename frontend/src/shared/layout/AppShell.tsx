import { createContext, use, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Outlet, useLocation } from "react-router";

import { ProfileGate } from "@/features/sign-up/ProfileGate";
import { useSignUpPending } from "@/shared/api/me";

import { SignInGate } from "@/shared/auth/SignInGate";
import { cn } from "@/shared/lib/cn";
import { MobileDrawer } from "@/shared/layout/MobileDrawer";
import { ShellTopRow } from "@/shared/layout/ShellTopRow";
import { Sidebar } from "@/shared/layout/Sidebar";

/** What a page calls to ask the shell for the wider column; the shell provides it, a lone page gets a no-op. */
const WideMainContext = createContext<(wide: boolean) => void>(() => undefined);

/**
 * A page with an aside (the two strategy pages) asks for a wider main (L26): its record column is what is tight, the
 * aside keeps its own width. The column is back at the common cap when the page is left, so every other page keeps it.
 */
export function useWideMain(): void {
  const setWide = use(WideMainContext);
  useLayoutEffect(() => {
    setWide(true);
    return () => setWide(false);
  }, [setWide]);
}

/**
 * The page frame. It is exactly one viewport tall (`#root` is 100% high), a flex row of the sidebar (from `lg`; below
 * it the hamburger in the top row opens the same pages in a drawer) and `main`, and only `main` scrolls. `min-h-0`
 * on the flex children lets them shrink below their content so the scroll happens inside `main` instead of on the
 * page. There is no top bar: what it held is the row at the top of `main` (`ShellTopRow`).
 *
 * The sign-in gate sits inside `main`, so the sidebar and the top row stay visible while it checks who is signed in
 * (`/health` is outside Access's check in the API) and the gate card fills the space `main` leaves over.
 *
 * `main` stays full width, so its scrollbar sits at the window edge. Every page lives in one centred column capped at
 * 1100 px (owner, 2026-11-24: "sin alargarse para ocupar todo el ancho"), with the same padding on every page so
 * nothing jumps when navigating, and a very wide screen adds margin around the content instead of stretching it.
 * A page with an aside (the two strategy pages) calls `useWideMain` and gets 1400 px instead (L26): its aside keeps its
 * 25 rem, so the extra width goes to the record column. Month by month needs about 1142 px of content beside the aside
 * to draw without scrolling sideways, so any cap from there up serves; 1400 leaves 22 % of slack. The column is back at
 * 1100 px when the page is left.
 *
 * Because `main` is the scroll container, a change of page puts it back at its
 * top; the browser does that for the window only, so a link followed from the
 * bottom of the terms would otherwise open the policy at its bottom.
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
 * sidebar, the hamburger, the exchange buttons and the mode badge wait for it
 * too: nothing of the panel to go to or act on. While `me` loads it shows, as
 * before sign-up existed.
 */
export function AppShell() {
  const { t } = useTranslation();
  const signUpPending = useSignUpPending();
  const { pathname } = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [wide, setWide] = useState(false);

  // `main` scrolls, not the window, so the browser's own reset on navigation never reaches it.
  useEffect(() => {
    if (mainRef.current !== null) mainRef.current.scrollTop = 0;
  }, [pathname]);

  const closeMenu = useCallback((restoreFocus: boolean) => {
    setMenuOpen(false);
    if (restoreFocus) menuRef.current?.focus();
  }, []);

  return (
    <div className="flex h-full bg-ground">
      {!signUpPending && <Sidebar />}
      <main ref={mainRef} className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-auto px-4 pb-10 pt-4 lg:px-10 lg:pb-14 lg:pt-6">
        <div className={cn("mx-auto flex w-full flex-1 flex-col", wide ? "max-w-[1400px]" : "max-w-[1100px]")}>
          <ShellTopRow pending={signUpPending} onOpenMenu={() => setMenuOpen(true)} menuRef={menuRef} />
          <SignInGate>
            <ProfileGate>
              <WideMainContext value={setWide}>
                <Outlet />
              </WideMainContext>
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
      {menuOpen && !signUpPending && <MobileDrawer onClose={closeMenu} />}
    </div>
  );
}
