import { create } from "zustand";

/**
 * Whether the signed-in user deleted their account in this page (account-deletion S5).
 *
 * Once it is true the app draws only the screen that says so: no route, no query. A read of `GET /api/me` after the
 * deletion would sign the same e-mail in again as a new, empty account, so nothing may ask the API anything. It is
 * kept in memory only, never in storage: a reload goes through Cloudflare Access again, which is what signing in
 * again means.
 */
interface AccountDeletedState {
  deleted: boolean;
  markDeleted: () => void;
}

export const useAccountDeletedStore = create<AccountDeletedState>()((set) => ({
  deleted: false,
  markDeleted: () => set({ deleted: true }),
}));
