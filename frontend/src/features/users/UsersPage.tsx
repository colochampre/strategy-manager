import { TriangleAlert } from "lucide-react";
import { type ReactNode, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { formatCuit } from "@/features/sign-up/cuit";
import { placementOf, StateDot, type TipPlacement } from "@/features/strategies/StrategyTableCells";
import { SuspensionDialog } from "@/features/users/SuspensionDialog";
import type { AdminUser } from "@/shared/api/admin-users";
import { useAdminUsers, useSetSuspension } from "@/shared/api/admin-users";
import { useMe } from "@/shared/api/me";
import { exchangeName } from "@/shared/exchanges/exchange-name";
import { useIsWide } from "@/shared/layout/useIsWide";
import { useTableFits } from "@/shared/layout/useTableFits";
import { cn } from "@/shared/lib/cn";
import { dateTimeText } from "@/shared/lib/figure-text";
import { Card } from "@/shared/ui/Card";
import { CountChip } from "@/shared/ui/CountChip";
import { PageHeader } from "@/shared/ui/PageHeader";
import { PAGER_BUTTON, TABLE_CELL, TABLE_HEAD } from "@/shared/ui/table-styles";
import { InfoTip, Tooltip } from "@/shared/ui/Tooltip";

/** Users a page (L47). The server answers the whole list, so the pages are cut here. */
export const USERS_PAGE_SIZE = 20;

/** Tailwind's `md`: the width from which the users can be a table at all. */
const MD_QUERY = "(min-width: 768px)";

/** A word with more to say in its tip: a dotted underline says there is one (the entry price's, L37). */
const HAS_TIP = "inline-flex cursor-help underline decoration-dotted underline-offset-2";

/** The row's one control: suspend or reactivate, asked first. The admin's own row has none (the server refuses it too). */
function SuspensionControl({ user, touch }: { user: AdminUser; touch: boolean }) {
  const { t } = useTranslation();
  const [asking, setAsking] = useState(false);
  const change = useSetSuspension();
  const suspending = user.suspended_at === null;

  const confirm = () => {
    change.mutate(
      { id: user.id, suspended: suspending },
      {
        onSuccess: (result) => {
          if (result.kind === "changed") setAsking(false);
        },
      },
    );
  };
  const cancel = () => {
    change.reset();
    setAsking(false);
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setAsking(true)}
        // The strategy table's Disable / Enable (ex13): loss to suspend, gain to reactivate, both of one width.
        className={cn(
          "inline-flex h-[30px] min-w-24 items-center justify-center rounded-lg border px-[11px] text-[13px] font-medium",
          touch && "min-h-11 self-start",
          suspending ? "border-loss/55 text-loss hover:bg-loss/10" : "border-gain/45 text-gain-bright hover:bg-gain/10",
        )}
      >
        {t(suspending ? "users.suspend" : "users.lift")}
      </button>
      {asking && (
        <SuspensionDialog
          email={user.email}
          suspending={suspending}
          pending={change.isPending}
          refusal={change.isError ? { kind: "unknown" } : change.data}
          onConfirm={confirm}
          onCancel={cancel}
        />
      )}
    </>
  );
}

/** Active or suspended, as a dot beside the e-mail; since when it is suspended is the tip (L47). */
function StateMark({ user, placement }: { user: AdminUser; placement: TipPlacement }) {
  const { t, i18n } = useTranslation();
  const suspended = user.suspended_at !== null;
  return (
    <StateDot
      tone={suspended ? "loss" : "gain"}
      label={
        user.suspended_at === null
          ? t("users.active")
          : t("users.suspendedSince", { date: dateTimeText(user.suspended_at, i18n.language) })
      }
      testId="admin-user-state"
      placement={placement}
    />
  );
}

/** The legal name, with the CUIT and the country in its tip; a user who has not signed up says so in a word (L47). */
function Identity({ user, placement }: { user: AdminUser; placement: TipPlacement }) {
  const { t } = useTranslation();
  const identity = user.identity;
  if (identity === null) {
    return (
      <Tooltip text={t("users.notSignedUp")} placement={placement} className={cn(HAS_TIP, "text-ink-3")}>
        <span data-testid="admin-user-identity">{t("users.notSignedUpShort")}</span>
      </Tooltip>
    );
  }
  const tip = t("users.identityTip", {
    cuit: formatCuit(identity.cuit),
    country: identity.country === "AR" ? t("signUp.countryAR") : identity.country,
  });
  return (
    <Tooltip text={tip} placement={placement} className={HAS_TIP}>
      <span data-testid="admin-user-identity">{`${identity.first_name} ${identity.last_name}`}</span>
    </Tooltip>
  );
}

/**
 * The exchanges a user holds a key on, with a mark on their left in a slot of its own, as the positions' pair has
 * (L48): a gain dot when every enabled pool has its key, a grey one with no key at all, and the loss triangle in its
 * place when an enabled pool has none, the exchanges named in its tip.
 */
function Keys({ user, placement }: { user: AdminUser; placement: TipPlacement }) {
  const { t, i18n } = useTranslation();
  const names = (exchanges: string[]) => exchanges.map((exchange) => exchangeName(t, i18n, exchange)).join(", ");
  const held = user.exchanges_with_key.length > 0;
  let mark: ReactNode;
  if (user.exchanges_with_no_key.length > 0) {
    const fault = t("users.poolWithNoKey", { exchanges: names(user.exchanges_with_no_key) });
    mark = (
      // The tip repeats the name, so it does not also describe the trigger.
      <Tooltip text={fault} describes={false} placement={placement}>
        <span role="img" aria-label={fault} data-testid="admin-user-no-key" className="inline-flex text-loss">
          <TriangleAlert aria-hidden="true" className="size-3.5" />
        </span>
      </Tooltip>
    );
  } else {
    mark = (
      <StateDot
        tone={held ? "gain" : "off"}
        label={t(held ? "users.keysAll" : "users.keysNone")}
        testId="admin-user-keys-mark"
        placement={placement}
      />
    );
  }
  return (
    // A block flex box, not an inline one: an inline box would sit on the icon's foot and lift the text beside it.
    <span data-testid="admin-user-keys" className="flex items-center gap-2">
      <span className="inline-flex w-3.5 shrink-0 justify-center">{mark}</span>
      {held ? names(user.exchanges_with_key) : <span className="text-ink-3">{t("users.noKeys")}</span>}
    </span>
  );
}

/** "Mode", and while the brake is on an (i) beside it saying that everyone trades in simulation (L47). */
function ModeLabel({ brake }: { brake: boolean }) {
  const { t } = useTranslation();
  return (
    <span className="inline-flex items-center gap-1">
      {t("users.mode")}
      {brake && (
        <span className="-my-1 inline-flex">
          <InfoTip label={t("users.brakeLabel")} text={t("users.brake")} placement="below" />
        </span>
      )}
    </span>
  );
}

interface ListProps {
  users: AdminUser[];
  /** The signed-in admin's e-mail: their own row has no control. */
  me: string | undefined;
  brake: boolean;
}

/** What a row says, the table's cells and the card's facts alike, so the two write each one the same way. */
function useFacts(user: AdminUser, placement: TipPlacement, me: string | undefined, touch: boolean) {
  const { t, i18n } = useTranslation();
  return {
    name:
      user.display_name === null ? (
        <span data-testid="admin-user-name" className="text-ink-3">
          {t("users.noName")}
        </span>
      ) : (
        <span data-testid="admin-user-name">{user.display_name}</span>
      ),
    identity: <Identity user={user} placement={placement} />,
    mode: <span data-testid="admin-user-mode">{t(user.mode === "LIVE" ? "status.live" : "status.simulation")}</span>,
    keys: <Keys user={user} placement={placement} />,
    subscriptions: <span data-testid="admin-user-subscriptions">{user.subscriptions}</span>,
    positions: <span data-testid="admin-user-positions">{user.open_positions}</span>,
    seen: <span data-testid="admin-user-seen">{dateTimeText(user.last_seen_at, i18n.language)}</span>,
    action:
      user.email === me ? (
        <span data-testid="admin-user-self" className="text-ink-3">
          {t("users.you")}
        </span>
      ) : (
        <SuspensionControl user={user} touch={touch} />
      ),
  };
}

const FIGURE = "text-right font-mono tabular-nums text-ink-2";
/** Nine columns take My subscriptions' 8 px sides at the same 13 px (L34), so the table fits the page's column (L47). */
const SIDES = "px-2 first:pl-3.5 last:pr-3";

function UserRow({ user, me, placement }: { user: AdminUser; me: string | undefined; placement: TipPlacement }) {
  const { t } = useTranslation();
  const facts = useFacts(user, placement, me, false);
  // No Name column: eight columns fit the page's column with room to spare, nine did not (L51). The name the user
  // chose is the e-mail's tip.
  const nameTip = user.display_name === null ? t("users.noName") : t("users.nameTip", { name: user.display_name });
  const cells: Array<[ReactNode, string?]> = [
    [
      <span className="flex items-center gap-2">
        <StateMark user={user} placement={placement} />
        <Tooltip text={nameTip} placement={placement} className={HAS_TIP}>
          <span data-testid="admin-user-email">{user.email}</span>
        </Tooltip>
      </span>,
      "text-ink",
    ],
    [facts.identity, "text-ink"],
    [facts.mode, "text-ink"],
    [facts.keys, "text-ink"],
    [facts.subscriptions, FIGURE],
    [facts.positions, FIGURE],
    [facts.seen, "font-mono tabular-nums text-ink-2"],
    [facts.action, "text-right"],
  ];
  return (
    <tr data-testid="admin-user-row">
      {cells.map(([content, className], index) => (
        <td key={index} className={cn(TABLE_CELL, SIDES, className)}>
          {content}
        </td>
      ))}
    </tr>
  );
}

/** The prototype's ex16 (RD.8): the boxed table of the panel's other tables, at their 13 px (L47). */
function UsersTable({ users, me, brake, labelledBy }: ListProps & { labelledBy: string }) {
  const { t } = useTranslation();
  const right = "text-right";
  const heads: Array<[ReactNode, string?]> = [
    [t("users.head.user")],
    [t("users.head.identity")],
    [<ModeLabel brake={brake} />],
    [t("users.keys")],
    [t("users.head.subscriptions"), right],
    [t("users.head.positions"), right],
    [t("users.seen")],
    [<span className="sr-only">{t("users.head.actions")}</span>],
  ];
  return (
    // The panel's boxed table without its sideways scroll: this table never scrolls (it turns into cards where it
    // does not fit), and a box that scrolls one way clips the other, so a tip opened in it (the brake's, under Mode)
    // grew a vertical scrollbar on a short list (L50). With nothing clipped, the heading row rounds its own corners.
    <div className="rounded-lg border border-rule">
      <table aria-labelledby={labelledBy} className="w-full border-collapse">
        <thead>
          <tr>
            {heads.map(([content, className], index) => (
              <th
                key={index}
                scope="col"
                className={cn(
                  TABLE_HEAD,
                  SIDES,
                  index === 0 && "rounded-tl-[7px]",
                  index === heads.length - 1 && "rounded-tr-[7px]",
                  className,
                )}
              >
                {content}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="text-left font-sans">
          {users.map((user, index) => (
            <UserRow key={user.id} user={user} me={me} placement={placementOf(index, users.length)} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

const LABEL = "text-[10px] uppercase tracking-[0.09em] text-ink-3";

/** One user where the table does not fit: the e-mail and its state dot in the head, the facts labelled beneath. */
function UserCard({ user, me, brake }: { user: AdminUser; me: string | undefined; brake: boolean }) {
  const { t } = useTranslation();
  const facts = useFacts(user, "above", me, true);
  const labelled: Array<[string, ReactNode, ReactNode?]> = [
    ["name", t("users.head.name"), facts.name],
    ["identity", t("users.head.identity"), facts.identity],
    ["mode", <ModeLabel brake={brake} />, facts.mode],
    ["keys", t("users.keys"), facts.keys],
    ["subscriptions", t("users.subscriptions"), facts.subscriptions],
    ["positions", t("users.positions"), facts.positions],
    ["seen", t("users.seen"), facts.seen],
  ];
  return (
    <article
      aria-label={user.email}
      data-testid="admin-user-row"
      className="flex min-w-0 flex-col gap-2.5 rounded-lg border border-rule bg-panel p-3.5"
    >
      <div className="flex min-w-0 items-center gap-2 font-display text-base font-semibold text-ink">
        <StateMark user={user} placement="below-start" />
        <span data-testid="admin-user-email" className="min-w-0 break-words">
          {user.email}
        </span>
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-[13px] text-ink sm:grid-cols-4">
        {labelled.map(([key, label, value]) => (
          <div key={key} className="min-w-0">
            <dt className={LABEL}>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {facts.action}
    </article>
  );
}

/** The table where its box holds it, the cards where it does not (L45), so no column runs past the card. */
function UsersView(props: ListProps & { labelledBy: string }) {
  const wide = useIsWide(MD_QUERY);
  const { ref, fits } = useTableFits();
  if (wide && fits) {
    return (
      <div ref={ref}>
        <UsersTable {...props} />
      </div>
    );
  }
  return (
    <div ref={ref} className="flex flex-col gap-4">
      {props.users.map((user) => (
        <UserCard key={user.id} user={user} me={props.me} brake={props.brake} />
      ))}
    </div>
  );
}

function UsersList() {
  const { t } = useTranslation();
  const users = useAdminUsers();
  const me = useMe();
  const headingId = useId();
  const [page, setPage] = useState(0);

  if (users.status === "pending") return <p className="text-sm text-ink-2">{t("users.loading")}</p>;
  if (users.status === "error") {
    return (
      <p role="alert" className="text-sm text-loss">
        {t("users.error")}
      </p>
    );
  }

  const pages = Math.max(1, Math.ceil(users.data.length / USERS_PAGE_SIZE));
  // A list that shrank under the page on screen shows its last page, never an empty one.
  const current = Math.min(page, pages - 1);
  const shown = users.data.slice(current * USERS_PAGE_SIZE, (current + 1) * USERS_PAGE_SIZE);

  return (
    <Card
      title={t("users.title")}
      headingId={headingId}
      dense
      action={<CountChip testId="admin-users-count">{t("users.count", { count: users.data.length })}</CountChip>}
    >
      {/* The table, then the pager 6 px under it, as the closed trades lay theirs out. */}
      <div>
        <UsersView users={shown} me={me.data?.email} brake={me.data?.dryRunBrake === true} labelledBy={headingId} />
        <nav aria-label={t("users.pagination")} className="mt-1.5 flex flex-wrap items-center gap-3">
          <button type="button" disabled={current === 0} onClick={() => setPage(current - 1)} className={PAGER_BUTTON}>
            {t("users.previous")}
          </button>
          <span className="font-mono text-xs text-ink-2">{t("users.page", { page: current + 1, pages })}</span>
          <button
            type="button"
            disabled={current >= pages - 1}
            onClick={() => setPage(current + 1)}
            className={PAGER_BUTTON}
          >
            {t("users.next")}
          </button>
        </nav>
      </div>
    </Card>
  );
}

/**
 * Every user with their state, for the admin (decision 8): enough to support someone and to understand a
 * discrepancy, and no amount and no performance. The mode shown is the one the user chose, so under the brake the
 * Mode heading's (i) says it is not the one they trade in.
 */
export function UsersPage() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        crumbs={[{ label: t("nav.admin") }, { label: t("users.title") }]}
        title={t("users.title")}
        subtitle={t("pageHeader.users")}
      />
      <UsersList />
    </div>
  );
}
