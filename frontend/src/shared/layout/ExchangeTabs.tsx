import { useTranslation } from "react-i18next";

import { useCredentials } from "@/shared/api/credentials";
import { usePools } from "@/shared/api/pools";
import { useTokenStore } from "@/shared/auth/token-store";
import { KeyMark } from "@/shared/credentials/KeyMark";
import { keyMark, keyState, knownPools, poolOn } from "@/shared/credentials/key-state";
import { ExchangeWordmark } from "@/shared/exchanges/ExchangeWordmark";
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
 *
 * Each tab says, under its name, what the owner has to know about that exchange's
 * key: `read-only`, or `no key`. The word comes from the same function the
 * Settings card uses, with the same inputs. While the credentials load or fail
 * there is no mark: no mark is a claim of nothing, and never "the key is fine".
 *
 * The name is the exchange's own logotype, dimmed on every tab but the selected
 * one, or its capitalised name where there is no logotype (owner decision 77).
 *
 * Every tab holds the same three-row grid (design § E), so the name sits at the
 * same height with a mark and without one. Below `lg` the tabs share the row's
 * whole width; from `lg` they keep their own.
 */
export function ExchangeTabs({ className }: ExchangeTabsProps) {
  const token = useTokenStore((state) => state.token);
  if (token === null) return null;
  return <ExchangeTabsBar className={className} />;
}

function ExchangeTabsBar({ className }: ExchangeTabsProps) {
  const { t } = useTranslation();
  const scope = useExchangeScope();
  const credentials = useCredentials();
  const pools = usePools();

  /** Only a credentials read that succeeded can say anything about a key. */
  const markOf = (exchange: string) => {
    if (credentials.status !== "success") return null;
    const entry = credentials.data.find((row) => row.exchange === exchange);
    return keyMark(keyState(entry, poolOn(exchange, knownPools(pools))));
  };

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
          const mark = markOf(exchange);
          return (
            <button
              key={exchange}
              type="button"
              aria-pressed={selected}
              onClick={() => scope.select(exchange)}
              className={cn(
                "min-w-fit flex-1 whitespace-nowrap rounded-md px-3.5 text-sm transition-colors lg:flex-none",
                selected
                  ? "bg-panel-2 font-semibold text-ink"
                  : "text-ink-3 hover:bg-panel-2 hover:text-ink",
              )}
            >
              <span className="grid min-h-13 grid-rows-[minmax(0,1fr)_auto_minmax(0,1fr)] justify-items-center">
                <span className="row-start-2 flex h-5 items-center leading-5">
                  <ExchangeWordmark exchange={exchange} className={cn("h-3.5", !selected && "opacity-55")} />
                </span>
                {mark !== null && (
                  <>
                    {" "}
                    <KeyMark mark={mark} variant="tab" className="row-start-3 self-start" />
                  </>
                )}
              </span>
            </button>
          );
        })}
    </nav>
  );
}
