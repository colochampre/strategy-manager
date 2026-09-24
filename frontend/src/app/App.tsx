import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { BookingsListView } from "@/features/bookings/BookingsListView";
import { TokenGate } from "@/shared/auth/TokenGate";
import { cn } from "@/shared/lib/cn";

type NavKey = "dashboard" | "strategies" | "settings" | "bookings";

const NAV_ITEMS: readonly NavKey[] = ["dashboard", "strategies", "settings", "bookings"] as const;
const DEFAULT_NAV_ITEM: NavKey = "dashboard";

function isNavKey(value: string): value is NavKey {
  return (NAV_ITEMS as readonly string[]).includes(value);
}

/** No router library is added for a four-view shell (design.md § 12) --
 * the existing `href="#..."` anchors drive this seed/update instead. */
function navKeyFromHash(hash: string): NavKey {
  const candidate = hash.replace(/^#/, "");
  return isNavKey(candidate) ? candidate : DEFAULT_NAV_ITEM;
}

export function App() {
  const { t, i18n } = useTranslation();
  const [active, setActive] = useState<NavKey>(() => navKeyFromHash(window.location.hash));

  useEffect(() => {
    const handleHashChange = () => {
      setActive(navKeyFromHash(window.location.hash));
    };
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  const toggleLanguage = () => {
    void i18n.changeLanguage(i18n.resolvedLanguage === "es" ? "en" : "es");
  };

  return (
    <div className="flex min-h-full flex-col lg:flex-row">
      {/* Sidebar on large screens */}
      <aside className="hidden w-56 shrink-0 border-r border-edge bg-surface-900 lg:flex lg:flex-col">
        <div className="px-5 py-6">
          <span className="text-sm font-semibold tracking-wide text-ink-100">
            {t("app.name")}
          </span>
        </div>
        <nav aria-label={t("nav.dashboard")} className="flex flex-col gap-1 px-3">
          {NAV_ITEMS.map((item) => (
            <a
              key={item}
              href={`#${item}`}
              className={cn(
                "rounded-md px-3 py-2 text-sm transition-colors",
                item === active
                  ? "bg-surface-800 text-ink-100"
                  : "text-ink-500 hover:bg-surface-850 hover:text-ink-300",
              )}
            >
              {t(`nav.${item}`)}
            </a>
          ))}
        </nav>
      </aside>

      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-edge bg-surface-900 px-4 py-3">
          <span className="text-sm font-semibold text-ink-100 lg:hidden">{t("app.name")}</span>
          <div className="ml-auto flex items-center gap-3">
            <span className="rounded-full bg-surface-800 px-2.5 py-1 text-xs text-idle">
              {t("status.dryRun")}
            </span>
            <button
              type="button"
              onClick={toggleLanguage}
              className="rounded-md px-2 py-1 text-xs uppercase text-ink-500 hover:text-ink-100"
            >
              {i18n.resolvedLanguage === "es" ? "en" : "es"}
            </button>
          </div>
        </header>

        <main className="flex-1 p-4 pb-20 lg:pb-4">
          <h1 className="mb-4 text-lg font-semibold">{t(`nav.${active}`)}</h1>
          {active === "bookings" && (
            <TokenGate>
              <BookingsListView />
            </TokenGate>
          )}
        </main>
      </div>

      {/* Bottom bar on small screens */}
      <nav
        aria-label={t("nav.dashboard")}
        className="fixed inset-x-0 bottom-0 flex border-t border-edge bg-surface-900 lg:hidden"
      >
        {NAV_ITEMS.map((item) => (
          <a
            key={item}
            href={`#${item}`}
            className={cn(
              "flex-1 py-3 text-center text-xs transition-colors",
              item === active ? "text-ink-100" : "text-ink-500",
            )}
          >
            {t(`nav.${item}`)}
          </a>
        ))}
      </nav>
    </div>
  );
}
