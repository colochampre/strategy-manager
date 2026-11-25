import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { createSafeStorage } from "@/shared/auth/safe-storage";

/**
 * Whether the panel hides the user's own money (S1, "Ocultar saldos"): one choice for every page, kept in the browser
 * through `safe-storage` so a reload keeps it and a blocked `localStorage` never breaks the page. It is a preference of
 * this browser only; nothing about it reaches the server.
 */
export const HIDDEN_STORAGE_KEY = "sm.hidden";

interface HiddenState {
  hidden: boolean;
  setHidden: (hidden: boolean) => void;
  toggle: () => void;
}

export const useHiddenStore = create<HiddenState>()(
  persist(
    (set) => ({
      hidden: false,
      setHidden: (hidden) => set({ hidden }),
      toggle: () => set((state) => ({ hidden: !state.hidden })),
    }),
    {
      name: HIDDEN_STORAGE_KEY,
      storage: createJSONStorage(() => createSafeStorage()),
      partialize: (state) => ({ hidden: state.hidden }),
      // Storage is untrusted: only a real `true` hides, so a wrong-typed value never masks the panel by accident.
      merge: (persisted, current) => ({
        ...current,
        hidden: (persisted as { hidden?: unknown } | null | undefined)?.hidden === true,
      }),
    },
  ),
);
