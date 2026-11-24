import { type KeyboardEvent, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { DrawerNavigation } from "@/shared/layout/Sidebar";

interface MobileDrawerProps {
  /** Closes the drawer. `restoreFocus` is false when a link was followed: the page that opens takes the focus. */
  onClose: (restoreFocus: boolean) => void;
}

const FOCUSABLE = "a[href], button:not([disabled]), [tabindex]:not([tabindex='-1'])";

/**
 * The phone's navigation: the sidebar in a dialog that slides in from the left over a scrim that fades. Focus moves
 * into it on opening and stays there (Tab wraps); Escape, the close button, the scrim and any followed link close it.
 * Under `prefers-reduced-motion` it simply appears.
 */
export function MobileDrawer({ onClose }: MobileDrawerProps) {
  const { t } = useTranslation();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  // The latest `onClose`, so the listener below is bound once and the focus is moved in once.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current(true);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const keepFocusInside = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab" || dialogRef.current === null) return;
    const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
      (item) => item.closest("[inert]") === null,
    );
    const first = items[0];
    const last = items[items.length - 1];
    if (first === undefined || last === undefined) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div className="fixed inset-0 z-40 lg:hidden">
      <div
        data-testid="drawer-scrim"
        aria-hidden="true"
        onClick={() => onClose(true)}
        className="absolute inset-0 animate-scrim-in bg-ground/75 motion-reduce:animate-none"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={t("nav.menu")}
        onKeyDown={keepFocusInside}
        className="absolute inset-y-0 left-0 w-75 max-w-[85vw] animate-drawer-in overflow-y-auto border-r border-rule bg-panel shadow-2xl motion-reduce:animate-none"
      >
        <DrawerNavigation onNavigate={() => onClose(false)} onClose={() => onClose(true)} closeRef={closeRef} />
      </div>
    </div>
  );
}
