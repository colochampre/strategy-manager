import { useTranslation } from "react-i18next";

import { BookingsListView } from "@/features/bookings/BookingsListView";
import { usePendingBookings } from "@/features/bookings/usePendingBookings";
import type { ExchangeScope } from "@/shared/scope/exchange-store";

export type RailPlacement = "right-rail" | "in-flow";

interface DecisionRailProps {
  scope: ExchangeScope;
  /** Where the page put the rail; it is a label for the layout, the page decides the position. */
  placement: RailPlacement;
}

/**
 * How many of the exchange's proposals are pending: 0 until the list has
 * arrived, and 0 when it failed, so neither state can show an amber figure.
 */
function usePendingCount(exchange: string): number {
  const bookings = usePendingBookings();
  if (bookings.status !== "success") return 0;
  return bookings.data.filter((proposal) => proposal.exchange === exchange).length;
}

/** One of the four places amber means "needs your decision"; nothing renders at zero. */
function PendingCount({ exchange }: { exchange: string }) {
  const { t } = useTranslation();
  const count = usePendingCount(exchange);
  if (count === 0) return null;
  return (
    <span data-testid="pending-count" className="font-mono text-xs text-decision">
      {t("overview.decisionRail.pending", { count })}
    </span>
  );
}

function ReadyRail({ exchange }: { exchange: string }) {
  const { t } = useTranslation();
  const count = usePendingCount(exchange);

  return (
    <>
      {count > 0 && <p className="text-[13px] text-ink-2">{t("overview.decisionRail.explainer")}</p>}
      <BookingsListView exchange={exchange} emptyText={t("overview.decisionRail.empty")} />
    </>
  );
}

/**
 * "Needs your decision": the pending venue-close bookings of the selected
 * exchange (owner decision 3), through the existing list, card and dialogs.
 *
 * It only renders bookings once the scope is KNOWN. While pools load, or when
 * they fail, it says so instead: the exchange tabs claim a filter, and showing
 * every exchange's bookings under them would contradict it. An approve button
 * on another exchange's proposal is the cost of that mistake.
 *
 * The `aside` is one element in every state, so a caller holding it while the
 * scope resolves is not left with a detached node.
 */
export function DecisionRail({ scope, placement }: DecisionRailProps) {
  const { t } = useTranslation();
  const exchange = scope.status === "ready" ? scope.exchange : null;

  return (
    <aside
      aria-labelledby="decision-rail-title"
      data-placement={placement}
      className="flex min-w-0 flex-col gap-3.5 rounded-lg border border-rule bg-panel p-4 lg:p-6"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="decision-rail-title" className="font-display text-base font-semibold text-ink">
          {t("overview.decisionRail.title")}
        </h2>
        {exchange !== null && <PendingCount exchange={exchange} />}
      </div>
      {scope.status === "loading" && (
        <p role="status" className="text-sm text-ink-3">
          {t("overview.decisionRail.scopeLoading")}
        </p>
      )}
      {scope.status === "error" && (
        <p role="alert" className="rounded-md border border-loss bg-panel p-4 text-sm text-ink-2">
          {t("overview.decisionRail.scopeError")}
        </p>
      )}
      {scope.status === "ready" && exchange === null && (
        <p className="text-sm text-ink-3">{t("overview.decisionRail.noExchanges")}</p>
      )}
      {exchange !== null && <ReadyRail exchange={exchange} />}
    </aside>
  );
}
