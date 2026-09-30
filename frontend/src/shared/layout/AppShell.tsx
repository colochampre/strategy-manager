import { Outlet } from "react-router";

import { TokenGate } from "@/shared/auth/TokenGate";
import { BottomNav } from "@/shared/layout/BottomNav";
import { SideNav } from "@/shared/layout/SideNav";
import { TopBar } from "@/shared/layout/TopBar";

/**
 * The page frame. It is exactly one viewport tall (`#root` is 100% high), a
 * flex column of top bar, body and (on phones) bottom bar, and only `main`
 * scrolls. `min-h-0` on the flex children lets them shrink below their
 * content so the scroll happens inside `main` instead of on the page.
 *
 * The token gate sits inside `main`, so the badge and navigation stay visible
 * while locked (`/health` needs no token) and the gate card fills the space
 * `main` leaves over.
 *
 * `main` stays full width, so its scrollbar sits at the window edge. Every page
 * lives in one centred column capped at 90rem (decision 38), so a very wide
 * screen adds margin around the content instead of stretching it, and the
 * space between the pool panel and the decision rail never grows.
 */
export function AppShell() {
  return (
    <div className="flex h-full flex-col bg-ground">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <SideNav />
        <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-auto p-4 lg:px-9 lg:py-7">
          <div className="mx-auto flex w-full max-w-[90rem] min-h-0 flex-1 flex-col">
            <TokenGate>
              <Outlet />
            </TokenGate>
          </div>
        </main>
      </div>
      <BottomNav />
    </div>
  );
}
