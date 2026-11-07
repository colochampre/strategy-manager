import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { CodeEntry } from "@/features/strategies/CodeEntry";
import { PublicFigures, PublicOrigin } from "@/features/strategies/PublicFigures";
import { useMe } from "@/shared/api/me";
import { usePublicStrategies } from "@/shared/api/public-strategies";
import type { PublicStrategy } from "@/shared/api/types";

function PublicStrategyRow({ strategy }: { strategy: PublicStrategy }) {
  return (
    <li data-testid="public-strategy-row" className="flex flex-col gap-3 rounded-md border border-rule bg-panel px-4 py-3">
      <div className="flex min-w-0 flex-col gap-0.5">
        <Link
          to={`/strategies/explore/${strategy.id}`}
          className="font-display text-base font-semibold text-gain hover:text-gain-bright"
        >
          {strategy.name}
        </Link>
        <PublicOrigin strategy={strategy} />
      </div>
      <PublicFigures strategy={strategy} />
    </li>
  );
}

/**
 * Every public strategy, for anyone signed in: a user with no key browses it the same (decision 13). Under the
 * server's brake nobody trades live, so the figures carry no capital, and the page says why. "I have a code" sits
 * above the list whatever its state, since a strategy shared by a code is on no list.
 */
export function ExplorePage() {
  return (
    <div className="flex flex-col gap-3">
      <CodeEntry />
      <PublicList />
    </div>
  );
}

function PublicList() {
  const { t } = useTranslation();
  const strategies = usePublicStrategies();
  const me = useMe();

  if (strategies.status === "pending") return <p className="text-sm text-ink-2">{t("strategies.explore.loading")}</p>;
  if (strategies.status === "error") {
    return (
      <p role="alert" className="text-sm text-loss">
        {t("strategies.explore.error")}
      </p>
    );
  }
  if (strategies.data.length === 0) return <p className="text-sm text-ink-2">{t("strategies.explore.empty")}</p>;

  return (
    <>
      {me.data?.dryRunBrake === true && <p className="text-sm text-ink-2">{t("strategies.explore.brake")}</p>}
      <ul className="flex flex-col gap-3">
        {strategies.data.map((strategy) => (
          <PublicStrategyRow key={strategy.id} strategy={strategy} />
        ))}
      </ul>
    </>
  );
}
