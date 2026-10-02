import { useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ArchivedToggle } from "@/features/strategies/ArchivedToggle";
import { StrategyRow } from "@/features/strategies/StrategyRow";
import { useStrategies } from "@/shared/api/strategies";
import { useExchangeScope } from "@/shared/scope/exchange-store";

/**
 * The Strategies container: the selected exchange's strategies, archived ones
 * only when asked.
 *
 * Nothing renders until the exchange scope is KNOWN, as on the Overview: a
 * list that cannot tell which exchange it shows would claim a filter that is
 * not applied. A failed or malformed list is an error the operator can see,
 * never an empty list.
 */
export function StrategiesPage() {
  const { t } = useTranslation();
  const scope = useExchangeScope();
  const [includeArchived, setIncludeArchived] = useState(false);
  const strategies = useStrategies(includeArchived);

  const exchange = scope.status === "ready" ? scope.exchange : null;

  let body: ReactNode;
  if (scope.status === "loading") {
    body = (
      <p role="status" className="text-sm text-ink-3">
        {t("strategies.scopeLoading")}
      </p>
    );
  } else if (scope.status === "error") {
    body = (
      <p role="alert" className="text-sm text-ink-2">
        {t("strategies.scopeError")}
      </p>
    );
  } else if (exchange === null) {
    body = <p className="text-sm text-ink-3">{t("strategies.noExchanges")}</p>;
  } else if (strategies.status === "pending") {
    body = (
      <p role="status" className="text-sm text-ink-3">
        {t("strategies.loading")}
      </p>
    );
  } else if (strategies.status === "error") {
    body = (
      <p role="alert" className="rounded-md border border-loss bg-panel p-4 text-sm text-ink-2">
        {t("strategies.error")}
      </p>
    );
  } else {
    const rows = strategies.data.filter((strategy) => strategy.exchange === exchange);
    body =
      rows.length === 0 ? (
        <p className="text-sm text-ink-3">{t("strategies.empty")}</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {rows.map((strategy) => (
            <StrategyRow key={strategy.id} strategy={strategy} />
          ))}
        </ul>
      );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h1 className="font-display text-2xl font-bold text-ink">{t("strategies.title")}</h1>
        <div className="flex flex-wrap items-center gap-x-4">
          <ArchivedToggle checked={includeArchived} onChange={setIncludeArchived} />
        </div>
      </div>
      {body}
    </div>
  );
}
