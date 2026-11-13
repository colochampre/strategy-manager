import { type FormEvent, useId, useState } from "react";
import { LogOut, UserPlus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { maxLeverage } from "@/features/strategies/stop-level";
import { entryRefusal } from "@/features/strategies/entry-refusal";
import { LeaveDialog } from "@/features/strategies/LeaveDialog";
import { LeverageSlider } from "@/features/strategies/LeverageSlider";
import { SeatSettings } from "@/features/strategies/SeatSettings";
import { ShareAmount } from "@/features/strategies/ShareAmount";
import { ShareSlider } from "@/features/strategies/ShareSlider";
import { leverageProblem, useLeverageDraft } from "@/features/strategies/useLeverageDraft";
import { DRAFT_REFUSAL_TEXT, useShareDraft } from "@/features/strategies/useShareDraft";
import { ApiError } from "@/shared/api/client";
import { NO_ENTRY } from "@/shared/api/entry";
import { useMe } from "@/shared/api/me";
import { usePools } from "@/shared/api/pools";
import { useHeldSubscriptions, useLeaveSubscription, useSubscribe } from "@/shared/api/subscriptions";
import type { HeldSubscription, PublicStrategy } from "@/shared/api/types";
import { DANGER_CONTROL } from "@/shared/ui/danger-control";
import { exchangeName } from "@/shared/exchanges/exchange-name";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";
import { StatusButton } from "@/shared/ui/StatusButton";

/** The share the form starts from: none (decision 39). It is never sent; the user types how much to use. */
const STARTING_SHARE = "0";
/** The leverage the form starts from: the API's own default. */
const STARTING_LEVERAGE = 1;
const LINK = "text-sm text-gain hover:text-gain-bright";
/** The frame of the page's settings column, the same as Strategy settings on an own strategy. */
const ASIDE = "flex flex-col gap-2 self-start rounded-lg border border-rule bg-panel p-5";

/**
 * The text of a refused subscribe: the status and the code decide, never the server's wording. A dead code and too
 * many wrong codes say so; a 404 keeps its own text, whatever the reader entered with.
 */
function refusalText(error: unknown): string {
  const byEntry = entryRefusal(error, NO_ENTRY);
  if (byEntry !== null) return byEntry;
  if (error instanceof ApiError) {
    if (error.status === 422) return "strategies.detail.share.outOfRange";
    if (error.status === 404) return "strategies.subscribe.refused.gone";
    if (error.code === "NO_POOL_FOR_MARKET") return "strategies.subscribe.refused.needsKey";
    if (error.code === "ALREADY_SUBSCRIBED") return "strategies.subscribe.refused.already";
    if (error.code === "STRATEGY_ARCHIVED") return "strategies.subscribe.refused.archived";
    if (error.code === "LEVERAGE_ABOVE_STOP_CAP") return "strategies.leverage.aboveCapRefused";
  }
  return "strategies.subscribe.refused.failed";
}

function SubscribeForm({ strategyId, stopLevel }: { strategyId: string; stopLevel: string }) {
  const { t } = useTranslation();
  const ids = { field: useId(), label: useId(), problem: useId() };
  const leverageIds = { field: useId(), label: useId(), problem: useId() };
  const subscribe = useSubscribe(strategyId);
  // What the strategy's stop allows: the control offers nothing above it.
  const max = maxLeverage(stopLevel);
  const leverage = useLeverageDraft(STARTING_LEVERAGE, undefined, max);
  // The share is read at the leverage being chosen in this same form (the one source), so the notional follows
  // it; a leverage that is not a value yet reads as x1 and asks for none.
  const { text, reading, handle, amount, edited, changeText, changeStep } = useShareDraft(
    strategyId,
    STARTING_SHARE,
    undefined,
    leverage.reading.valid ? leverage.reading.value : STARTING_LEVERAGE,
  );
  const leverageInfo = useInfoDisclosure();
  const busy = subscribe.isPending;

  const send = (event: FormEvent) => {
    event.preventDefault();
    if (reading.valid && leverage.reading.valid && !busy) {
      subscribe.mutate({ share: reading.canonical, leverage: leverage.reading.value });
    }
  };
  const submitText = t("strategies.subscribe.submit");
  const pendingText = t("strategies.subscribe.pending");

  return (
    <form onSubmit={send} className="flex flex-col gap-3">
      <label id={ids.label} htmlFor={ids.field} className="text-sm leading-5 text-ink-2">
        {t("strategies.detail.share.label")}
      </label>
      <ShareSlider
        fieldId={ids.field}
        labelId={ids.label}
        text={text}
        handle={handle}
        value={reading.valid ? reading.canonical : null}
        disabled={busy}
        invalid={!reading.valid && edited}
        describedBy={reading.valid ? undefined : ids.problem}
        onText={changeText}
        onHandle={changeStep}
        onStop={changeStep}
      />
      <ShareAmount view={amount} />
      {!reading.valid &&
        (edited ? (
          <p id={ids.problem} className="text-xs text-loss">
            {t(DRAFT_REFUSAL_TEXT[reading.refusal])}
          </p>
        ) : (
          <p id={ids.problem} className="text-xs text-ink-3">
            {t("strategies.detail.share.startHint")}
          </p>
        ))}
      <div className="flex items-start">
        <label id={leverageIds.label} htmlFor={leverageIds.field} className="text-sm leading-5 text-ink-2">
          {t("strategies.leverage.label")}
        </label>
        <InfoButton disclosure={leverageInfo} label={t("strategies.leverage.info")} />
      </div>
      <InfoText disclosure={leverageInfo}>
        <p className="text-xs text-ink-3">{t("strategies.leverage.hint")}</p>
      </InfoText>
      <LeverageSlider
        fieldId={leverageIds.field}
        labelId={leverageIds.label}
        text={leverage.text}
        handle={leverage.handle}
        value={leverage.reading.valid ? leverage.reading.value : null}
        disabled={busy}
        invalid={!leverage.reading.valid}
        describedBy={leverage.reading.valid ? undefined : leverageIds.problem}
        max={max}
        onText={leverage.changeText}
        onHandle={leverage.changeStep}
        onStop={leverage.changeStep}
      />
      {max < 20 && leverage.reading.valid && (
        <p className="text-xs text-ink-3">{t("strategies.leverage.capNote", { max })}</p>
      )}
      {!leverage.reading.valid && (
        <p id={leverageIds.problem} className="text-xs text-loss">
          {t(
            leverageProblem(leverage.reading.refusal, max).key,
            leverageProblem(leverage.reading.refusal, max).values,
          )}
        </p>
      )}
      <p className="text-xs text-ink-3">{t("strategies.subscribe.publicSum")}</p>
      <div>
        <StatusButton
          texts={[submitText, pendingText]}
          shown={busy ? pendingText : submitText}
          message={null}
          submit
          disabled={busy || !reading.valid || !leverage.reading.valid}
          icon={UserPlus}
          className="min-h-11 rounded-md bg-gain px-3 text-sm font-medium text-ground hover:opacity-90 disabled:opacity-50"
        />
      </div>
      {subscribe.isError && (
        <p role="alert" className="text-sm text-loss">
          {t(refusalText(subscribe.error))}
        </p>
      )}
    </form>
  );
}

function SubscribeBody({ strategy }: { strategy: PublicStrategy }) {
  const { t, i18n } = useTranslation();
  const me = useMe();
  const pools = usePools();
  const held = useHeldSubscriptions();
  const user = me.data;
  const poolList = pools.data;
  const subscriptions = held.data;

  // Whether the form may be offered depends on all three, so nothing is offered until all three are known.
  if (user === undefined || poolList === undefined || subscriptions === undefined) {
    if (me.isError || pools.isError || held.isError) {
      return (
        <p role="alert" className="text-sm text-loss">
          {t("strategies.subscribe.readFailed")}
        </p>
      );
    }
    return <p className="text-sm text-ink-2">{t("strategies.subscribe.reading")}</p>;
  }

  const mine = subscriptions.find((subscription) => subscription.strategy_id === strategy.id);
  if (mine?.authored === true || user.displayName === strategy.author_name) {
    return (
      <>
        <p className="text-sm text-ink-2">{t("strategies.subscribe.yours")}</p>
        <Link to={`/strategies/${strategy.id}`} className={LINK}>
          {t("strategies.subscribe.openYours")}
        </Link>
      </>
    );
  }
  // A seat that is not the author's is shown by `SubscribePanel` as `SeatPanel`, in place of this whole section;
  // the form never stands beside a seat, even for the render in which the two have read different data.
  if (mine !== undefined) return null;

  // A deleted key leaves its pool disabled, and a pool that is disabled cannot be subscribed through (decision 13).
  const reachable = poolList.some(
    (pool) =>
      pool.enabled &&
      pool.exchange === strategy.exchange &&
      pool.venue === strategy.venue &&
      pool.settlement_currency === strategy.settlement_currency,
  );
  if (!reachable) {
    return (
      <>
        <p className="text-sm text-ink-2">
          {t("strategies.subscribe.needsKey", { exchange: exchangeName(t, i18n, strategy.exchange) })}
        </p>
        <Link to="/settings" className={LINK}>
          {t("strategies.subscribe.addKey")}
        </Link>
      </>
    );
  }
  return <SubscribeForm strategyId={strategy.id} stopLevel={strategy.stop_loss_pct} />;
}

/**
 * The reader's own seat on a strategy that is not theirs: the share and leverage settings, each with its own
 * Save, and Leave. This is the one place a subscriber edits a seat; My subscriptions only summarises it.
 */
function SeatPanel({ strategy, seat }: { strategy: PublicStrategy; seat: HeldSubscription }) {
  const { t } = useTranslation();
  const titleId = useId();
  const [asking, setAsking] = useState(false);
  const leave = useLeaveSubscription(seat.strategy_id, seat.id);
  // A seat that is leaving takes no change and no second leave: the editors read as they stand.
  const active = seat.status === "ACTIVE";
  const openDialog = () => {
    leave.reset();
    setAsking(true);
  };
  return (
    <aside aria-labelledby={titleId} className={ASIDE}>
      <h2 id={titleId} className="font-display text-base font-semibold text-ink">
        {t("strategies.subscribe.seatTitle")}
      </h2>
      <SeatSettings
        strategy={{
          id: seat.strategy_id,
          subscription: seat,
          archived_at: null,
          // The seat's own row carries the level, so the cap holds even if the page was read before a change.
          stop_loss_pct: seat.stop_loss_pct,
        }}
      />
      {!active && <p className="text-sm text-ink-2">{t("strategies.subscriptions.leaving")}</p>}
      {active && (
        <div>
          <button type="button" onClick={openDialog} className={`${DANGER_CONTROL} w-full justify-center`}>
            <LogOut aria-hidden="true" className="size-4 shrink-0" />
            {t("strategies.subscriptions.leave")}
          </button>
        </div>
      )}
      {asking && (
        <LeaveDialog
          name={strategy.name}
          pending={leave.isPending}
          error={leave.error}
          onConfirm={() => leave.mutate(undefined, { onSuccess: () => setAsking(false) })}
          onCancel={() => setAsking(false)}
        />
      )}
    </aside>
  );
}

/**
 * The reader's own seat on a strategy that is not theirs, or undefined: no seat, the author's own, or either read
 * not in yet. The one rule for "this reader holds a seat", shared by the Subscribe section and the report views.
 */
export function useOwnSeat(strategy: PublicStrategy): HeldSubscription | undefined {
  const me = useMe();
  const held = useHeldSubscriptions();
  const mine = held.data?.find((subscription) => subscription.strategy_id === strategy.id);
  if (mine !== undefined && mine.authored !== true && me.data !== undefined && me.data.displayName !== strategy.author_name) {
    return mine;
  }
  return undefined;
}

/**
 * Where the signed-in user stands on a public strategy: its author, already holding it, missing a key on its
 * market, or free to subscribe. The figures beside it never depend on any of this. Either way it is the page's
 * settings column, an aside like Strategy settings on an own strategy.
 */
export function SubscribePanel({ strategy }: { strategy: PublicStrategy }) {
  const { t } = useTranslation();
  const titleId = useId();
  const seat = useOwnSeat(strategy);
  if (seat !== undefined) return <SeatPanel strategy={strategy} seat={seat} />;
  return (
    <aside aria-labelledby={titleId} className={ASIDE}>
      <h2 id={titleId} className="font-display text-base font-semibold text-ink">
        {t("strategies.subscribe.title")}
      </h2>
      <SubscribeBody strategy={strategy} />
    </aside>
  );
}
