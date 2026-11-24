import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { createSafeStorage } from "@/shared/auth/safe-storage";

/**
 * Whether the desktop sidebar is collapsed to its icons, kept in the browser through `safe-storage` so a reload
 * keeps it and a blocked `localStorage` (private mode) never breaks the page. A preference of this browser only.
 */
export const SIDEBAR_STORAGE_KEY = "sm.sidebar";

interface SidebarState {
  collapsed: boolean;
  setCollapsed: (collapsed: boolean) => void;
}

export const useSidebarStore = create<SidebarState>()(
  persist(
    (set) => ({
      collapsed: false,
      setCollapsed: (collapsed) => set({ collapsed }),
    }),
    {
      name: SIDEBAR_STORAGE_KEY,
      storage: createJSONStorage(() => createSafeStorage()),
      partialize: (state) => ({ collapsed: state.collapsed }),
    },
  ),
);
