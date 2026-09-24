import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { createSafeStorage } from "@/shared/auth/safe-storage";

/**
 * The admin bearer token, persisted to `localStorage` under this key so a
 * page reload does not force the operator to paste it again. It NEVER comes
 * from a Vite build-time env variable — see design.md §12 and this repo's
 * own guard test in `token-store.test.ts`, which scans the source tree for
 * that mistake.
 */
export const TOKEN_STORAGE_KEY = "sm.admin_token";

interface TokenState {
  token: string | null;
  setToken: (token: string) => void;
  clearToken: () => void;
}

export const useTokenStore = create<TokenState>()(
  persist(
    (set) => ({
      token: null,
      setToken: (token) => set({ token }),
      clearToken: () => set({ token: null }),
    }),
    {
      name: TOKEN_STORAGE_KEY,
      storage: createJSONStorage(() => createSafeStorage()),
    },
  ),
);
