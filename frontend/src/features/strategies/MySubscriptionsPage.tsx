import { LogOut } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { LeaveDialog } from "@/features/strategies/LeaveDialog";
import { PoolShareEditor } from "@/features/strategies/PoolShareEditor";
import { SubscriptionLeverageEditor } from "@/features/strategies/SubscriptionLeverageEditor";
import { readStored } from "@/features/strategies/share-value";
import { useHeldSubscriptions, useLeaveSubscription } from "@/shared/api/subscriptions";
import type { HeldSubscription } from "@/shared/api/types";
import { DANGER_CONTROL } from "@/shared/ui/danger-control";

const CONTROL = "min-h-11 rounded-md border border-rule px-3 text-sm text-ink-2 hover:bg-panel-2";

function SubscriptionRow({ held }: { held: HeldSubscription }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [asking, setAsking] = useState(false);
  const leave = useLeaveSubscription(held.strategy_id, held.id);
  const active = held.status === "ACTIVE";
  // A strategy turned private has no public page, so this row is the one place to manage its subscription.
  const managed = active && !held.authored;
  const author = held.authored
    ? t("strategies.subscriptions.yours")
    : held.author_name === null
      ? t("strategies.subscriptions.noAuthorName")
      : t("strategies.subscriptions.by", { name: held.author_name });

  const openDialog = () => {
    leave.reset();
    setAsking(true);
  };

  return (
    <li data-testid="subscription-row" className="flex flex-col gap-3 rounded-md border border-rule bg-panel px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <Link
            to={held.authored ? `/strategies/${held.strategy_id}` : `/strategies/explore/${held.strategy_id}`}
            className="font-display text-base font-semibold text-gain hover:text-gain-bright"
          >
            {held.strategy_name}
          </Link>
          <p data-testid="subscription-origin" className="text-xs text-ink-2">
            {`${author} · ${held.exchange} · ${held.venue} · ${held.settlement_currency}`}
          </p>
          <p data-testid="subscription-share" className="text-xs text-ink-2">
            {t("strategies.subscriptions.share", { share: readStored(held.allocation_percent) ?? held.allocation_percent })}
          </p>
        </div>
        {managed && (
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" aria-expanded={editing} onClick={() => setEditing(!editing)} className={CONTROL}>
              {t(editing ? "strategies.subscriptions.closeShare" : "strategies.subscriptions.changeShare")}
            </button>
            <button type="button" onClick={openDialog} className={DANGER_CONTROL}>
              <LogOut aria-hidden="true" className="size-4 shrink-0" />
              {t("strategies.subscriptions.leave")}
            </button>
          </div>
        )}
      </div>
      {!active && <p className="text-sm text-ink-2">{t("strategies.subscriptions.leaving")}</p>}
      {managed && editing && (
        <>
          <PoolShareEditor strategy={{ id: held.strategy_id, subscription: held, archived_at: null }} />
          <SubscriptionLeverageEditor strategy={{ id: held.strategy_id, subscription: held, archived_at: null }} />
        </>
      )}
      {asking && (
        <LeaveDialog
          name={held.strategy_name}
          pending={leave.isPending}
          error={leave.error}
          onConfirm={() => leave.mutate(undefined, { onSuccess: () => setAsking(false) })}
          onCancel={() => setAsking(false)}
        />
      )}
    </li>
  );
}

/**
 * What the signed-in user holds, live: the strategies they trade and the ones they are leaving. A failed read
 * is an error and never an empty list, because "you hold nothing" is a claim about real money.
 */
export function MySubscriptionsPage() {
  const { t } = useTranslation();
  const held = useHeldSubscriptions();

  if (held.status === "pending") return <p className="text-sm text-ink-2">{t("strategies.subscriptions.loading")}</p>;
  if (held.status === "error") {
    return (
      <p role="alert" className="text-sm text-loss">
        {t("strategies.subscriptions.error")}
      </p>
    );
  }
  if (held.data.length === 0) {
    return (
      <div className="flex flex-col items-start gap-2">
        <p className="text-sm text-ink-2">{t("strategies.subscriptions.empty")}</p>
        <Link to="/strategies/explore" className="text-sm text-gain hover:text-gain-bright">
          {t("strategies.subscriptions.explore")}
        </Link>
      </div>
    );
  }

  return (
    <ul className="flex flex-col gap-3">
      {held.data.map((subscription) => (
        <SubscriptionRow key={subscription.id} held={subscription} />
      ))}
    </ul>
  );
}
