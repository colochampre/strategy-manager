import { useTranslation } from "react-i18next";

import { useMe } from "@/shared/api/me";
import { ExchangeWordmark } from "@/shared/exchanges/ExchangeWordmark";
import { cn } from "@/shared/lib/cn";
import { useExchangeScope } from "@/shared/scope/exchange-store";

interface ExchangeTabsProps {
  className?: string | undefined;
}

/**
 * The exchange selector of the scoped routes, for anyone signed in. Until the
 * API has said who that is there is nothing to scope, and `GET /pools` would
 * only answer 401, so it renders nothing and asks for nothing; `ShellTopRow` mounts
 * it only on the scoped routes, which is why Settings never reads the scope.
 *
 * The row scrolls sideways and never wraps, so a long exchange list on a phone
 * cannot push the page taller than the viewport.
 *
 * A tab is the exchange's name and nothing else: the state of its key is shown
 * where keys are managed, not here (owner, 2026-11-24).
 *
 * The name is the exchange's own logotype, dimmed on every tab but the selected
 * one, or its capitalised name where there is no logotype (owner decision 77).
 *
 * Every tab is 36 px tall, as tall as the mode badge and the icon buttons beside
 * it, with the rule's border; the selected one is told apart by its background
 * alone. Below `lg` the tabs share the row's whole width; from `lg` they keep
 * their own.
 */
export function ExchangeTabs({ className }: ExchangeTabsProps) {
  const me = useMe();
  if (me.data === undefined) return null;
  return <ExchangeTabsBar className={className} />;
}

function ExchangeTabsBar({ className }: ExchangeTabsProps) {
  const { t } = useTranslation();
  const scope = useExchangeScope();

  return (
    <nav
      aria-label={t("scope.exchanges")}
      className={cn("flex min-w-0 items-center gap-2 overflow-x-auto", className)}
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
                "inline-flex h-9 min-w-fit flex-1 items-center justify-center whitespace-nowrap rounded-lg border border-rule px-4.5 text-sm transition-colors motion-reduce:transition-none lg:flex-none",
                selected ? "bg-panel-2 text-ink" : "bg-panel text-ink-3 hover:bg-panel-2 hover:text-ink",
              )}
            >
              <ExchangeWordmark exchange={exchange} className={cn("h-3.5", !selected && "opacity-55")} />
            </button>
          );
        })}
    </nav>
  );
}
