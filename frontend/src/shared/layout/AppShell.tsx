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
 */
export function AppShell() {
  return (
    <div className="flex h-full flex-col bg-ground">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <SideNav />
        <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-auto p-4 lg:px-9 lg:py-7">
          <TokenGate>
            <Outlet />
          </TokenGate>
        </main>
      </div>
      <BottomNav />
    </div>
  );
}
