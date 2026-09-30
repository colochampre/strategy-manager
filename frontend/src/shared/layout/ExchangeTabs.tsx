import { useTranslation } from "react-i18next";

import { useTokenStore } from "@/shared/auth/token-store";
import { cn } from "@/shared/lib/cn";
import { useExchangeScope } from "@/shared/scope/exchange-store";

interface ExchangeTabsProps {
  className?: string | undefined;
}

/**
 * The exchange selector of the scoped routes. While the token gate is locked
 * there is nothing to scope and `GET /pools` would only answer 401, so it
 * renders nothing and asks for nothing; `TopBar` mounts it only on the scoped
 * routes, which is why Settings never reads the scope.
 *
 * The row scrolls sideways and never wraps, so a long exchange list on a phone
 * cannot push the page taller than the viewport.
 */
export function ExchangeTabs({ className }: ExchangeTabsProps) {
  const token = useTokenStore((state) => state.token);
  if (token === null) return null;
  return <ExchangeTabsBar className={className} />;
}

function ExchangeTabsBar({ className }: ExchangeTabsProps) {
  const { t } = useTranslation();
  const scope = useExchangeScope();

  return (
    <nav
      aria-label={t("scope.exchanges")}
      className={cn("flex min-w-0 items-center gap-1 overflow-x-auto", className)}
    >
      {scope.status === "loading" && (
        <p role="status" className="whitespace-nowrap text-xs text-ink-3">
          {t("scope.loading")}
        </p>
      )}
      {scope.status === "error" && (
        <p role="alert" className="whitespace-nowrap text-xs text-loss">
          {t("scope.error")}
        </p>
      )}
      {scope.status === "ready" &&
        scope.options.map((exchange) => {
          const selected = exchange === scope.exchange;
          return (
            <button
              key={exchange}
              type="button"
              aria-pressed={selected}
              onClick={() => scope.select(exchange)}
              className={cn(
                "min-h-11 shrink-0 whitespace-nowrap rounded-md px-3.5 text-sm transition-colors",
                selected
                  ? "bg-panel-2 font-semibold text-ink"
                  : "text-ink-3 hover:bg-panel-2 hover:text-ink",
              )}
            >
              {exchange}
            </button>
          );
        })}
    </nav>
  );
}
