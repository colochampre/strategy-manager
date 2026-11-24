import { LogOut, PowerOff } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { CloseNowControl } from "@/features/positions/CloseNowControl";
import { DeleteAccountSection } from "@/features/settings/DeleteAccountSection";
import { DeleteKeyControl } from "@/features/settings/DeleteKeyControl";
import { ArchiveControl } from "@/features/strategies/ArchiveControl";
import { useEnableQuestion } from "@/features/strategies/EnableDialog";
import { LeaveDialog } from "@/features/strategies/LeaveDialog";
import { useCredentials } from "@/shared/api/credentials";
import { useOpenPositions, type OpenPosition } from "@/shared/api/positions";
import { useStrategies } from "@/shared/api/strategies";
import { useHeldSubscriptions, useLeaveSubscription } from "@/shared/api/subscriptions";
import type { HeldSubscription, Strategy } from "@/shared/api/types";
import { exchangeName } from "@/shared/exchanges/exchange-name";
import { DANGER_CONTROL } from "@/shared/ui/danger-control";
import { PageHeader } from "@/shared/ui/PageHeader";
import { ReportSection } from "@/shared/ui/ReportSection";

/** Where the sign-up form and the acceptance box send a user who will not go on (public-site PS.15). */
export const WAY_OUT_PATH = "/way-out";

const ROW = "flex flex-wrap items-center justify-between gap-3 py-2";

/**
 * Every way out, on one page a user reaches before signing up or accepting new terms (public-site PS.15, S1): their
 * open positions with Close now, their subscriptions with Leave, their own strategies with Disable then Archive,
 * their exchange keys, and the account's deletion. The navigation stays hidden (LS2), so this page names nothing
 * else of the panel. Each control is the one the rest of the panel uses; every route they call is open before
 * sign-up, disabling included (only with a body of exactly `{"enabled": false}`).
 */
export function WayOutPage() {
  const { t } = useTranslation();

  return (
    // The parts stack 4 apart, as every view's blocks do; the title alone steps 6 to them (L.13).
    <div className="flex max-w-3xl flex-col gap-4">
      <PageHeader
        crumbs={[{ label: t("wayOut.title") }]}
        title={t("wayOut.title")}
        subtitle={t("wayOut.intro")}
      />
      <Link to="/" className="mb-2 self-start text-sm text-ink-2 underline hover:text-ink">
        {t("wayOut.back")}
      </Link>
      <PositionsPart />
      <SeatsPart />
      <StrategiesPart />
      <KeysPart />
      <DeleteAccountSection />
    </div>
  );
}

/** A titled part of the page: its list once read, what it says when empty, and a notice when it cannot be read. */
function Part({ title, state, children }: { title: PartName; state: PartState; children?: ReactNode }) {
  const { t } = useTranslation();
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <h2 id={headingId} className="font-display text-base font-semibold text-ink">
        {t(`wayOut.${title}.title`)}
      </h2>
      <ReportSection>
        {state === "failed" && (
          <p role="alert" className="text-sm text-loss">
            {t("wayOut.readFailed")}
          </p>
        )}
        {state === "empty" && <p className="text-sm text-ink-2">{t(`wayOut.${title}.none`)}</p>}
        {state === "listed" && <ul className="flex flex-col divide-y divide-rule">{children}</ul>}
      </ReportSection>
    </section>
  );
}

type PartName = "positions" | "seats" | "strategies" | "keys";
/** Loading draws the title alone, so an empty list is never said before it is read. */
type PartState = "loading" | "failed" | "empty" | "listed";

function stateOf(isError: boolean, rows: readonly unknown[] | undefined): PartState {
  if (isError) return "failed";
  if (rows === undefined) return "loading";
  return rows.length === 0 ? "empty" : "listed";
}

function PositionsPart() {
  const open = useOpenPositions();
  const positions = open.data?.positions;
  return (
    <Part title="positions" state={stateOf(open.isError, positions)}>
      {positions?.map((position) => <PositionRow key={position.allocation_id} position={position} />)}
    </Part>
  );
}

/** The strategy, then its market, side and size as the venue reports them (LONG and SHORT read the same in both languages). */
function PositionRow({ position }: { position: OpenPosition }) {
  const detail = [position.markets.join(", "), position.side, position.size].filter((part) => part !== null && part !== "");
  return (
    <li className={ROW}>
      <div className="flex min-w-0 flex-col">
        <span className="text-sm font-medium text-ink">{position.strategy_name}</span>
        <span className="text-xs text-ink-3">{detail.join(" · ")}</span>
      </div>
      <CloseNowControl position={position} />
    </li>
  );
}

function SeatsPart() {
  const held = useHeldSubscriptions();
  // The author's own seat is not left: archiving the strategy ends it (`AUTHOR_CANNOT_LEAVE`).
  const seats = held.data?.filter((seat) => !seat.authored && seat.status !== "ENDED");
  return (
    <Part title="seats" state={stateOf(held.isError, seats)}>
      {seats?.map((seat) => <SeatRow key={seat.id} seat={seat} />)}
    </Part>
  );
}

function SeatRow({ seat }: { seat: HeldSubscription }) {
  const { t } = useTranslation();
  const [asking, setAsking] = useState(false);
  const leave = useLeaveSubscription(seat.strategy_id, seat.id);
  const ask = () => {
    leave.reset();
    setAsking(true);
  };
  return (
    <li className={ROW}>
      <span className="text-sm font-medium text-ink">{seat.strategy_name}</span>
      {seat.status === "ACTIVE" ? (
        <button type="button" onClick={ask} className={DANGER_CONTROL}>
          <LogOut aria-hidden="true" className="size-4 shrink-0" />
          {t("strategies.subscriptions.leave")}
        </button>
      ) : (
        <span className="text-xs text-ink-2">{t("wayOut.seats.leaving")}</span>
      )}
      {asking && (
        <LeaveDialog
          name={seat.strategy_name}
          pending={leave.isPending}
          error={leave.error}
          onConfirm={() => leave.mutate(undefined, { onSuccess: () => setAsking(false) })}
          onCancel={() => setAsking(false)}
        />
      )}
    </li>
  );
}

function StrategiesPart() {
  const own = useStrategies(false);
  const strategies = own.data?.filter((strategy) => strategy.archived_at === null);
  return (
    <Part title="strategies" state={stateOf(own.isError, strategies)}>
      {strategies?.map((strategy) => <StrategyRow key={strategy.id} strategy={strategy} />)}
    </Part>
  );
}

function StrategyRow({ strategy }: { strategy: Strategy }) {
  const { t } = useTranslation();
  const question = useEnableQuestion(strategy);
  return (
    <li className={ROW}>
      <div className="flex min-w-0 flex-col">
        <span className="text-sm font-medium text-ink">{strategy.name}</span>
        {strategy.enabled && <span className="text-xs text-ink-3">{t("wayOut.strategies.archiveFirst")}</span>}
      </div>
      {strategy.enabled ? (
        <button type="button" onClick={question.ask} disabled={question.busy} className={DANGER_CONTROL}>
          <PowerOff aria-hidden="true" className="size-4 shrink-0" />
          {t("wayOut.strategies.disable")}
        </button>
      ) : (
        <div>
          <ArchiveControl strategy={strategy} />
        </div>
      )}
      {question.dialog}
    </li>
  );
}

function KeysPart() {
  const { t, i18n } = useTranslation();
  const credentials = useCredentials();
  const stored = credentials.data?.flatMap((entry) => (entry.status === "STORED" ? [entry] : []));
  return (
    <Part title="keys" state={stateOf(credentials.isError, stored)}>
      {stored?.map((entry) => {
        const name = exchangeName(t, i18n, entry.exchange);
        return (
          <li key={entry.exchange} className={ROW}>
            <span className="text-sm font-medium text-ink">
              {name} <span className="text-xs text-ink-3">···{entry.last4}</span>
            </span>
            <DeleteKeyControl exchange={entry.exchange} name={name} last4={entry.last4} />
          </li>
        );
      })}
    </Part>
  );
}
