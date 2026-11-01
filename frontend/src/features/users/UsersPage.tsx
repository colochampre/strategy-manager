import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { AdminUser } from "@/shared/api/admin-users";
import { useAdminUsers } from "@/shared/api/admin-users";
import { useMe } from "@/shared/api/me";
import { dateTimeText } from "@/shared/lib/figure-text";

interface FactProps {
  label: string;
  testId: string;
  children: ReactNode;
}

function Fact({ label, testId, children }: FactProps) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd data-testid={testId} className="text-sm text-ink">
        {children}
      </dd>
    </div>
  );
}

function UserRow({ user }: { user: AdminUser }) {
  const { t, i18n } = useTranslation();
  return (
    <li data-testid="admin-user-row" className="flex flex-col gap-3 rounded-md border border-rule bg-panel px-4 py-3">
      <div className="flex min-w-0 flex-col gap-0.5">
        <p data-testid="admin-user-email" className="break-words font-display text-base font-semibold text-ink">
          {user.email}
        </p>
        <p data-testid="admin-user-name" className="text-xs text-ink-2">
          {user.display_name ?? t("users.noName")}
        </p>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3 lg:grid-cols-5">
        <Fact label={t("users.mode")} testId="admin-user-mode">
          {t(user.mode === "LIVE" ? "status.live" : "status.simulation")}
        </Fact>
        <Fact label={t("users.keys")} testId="admin-user-keys">
          {user.exchanges_with_key.length === 0 ? t("users.noKeys") : user.exchanges_with_key.join(", ")}
        </Fact>
        <Fact label={t("users.subscriptions")} testId="admin-user-subscriptions">
          {user.subscriptions}
        </Fact>
        <Fact label={t("users.positions")} testId="admin-user-positions">
          {user.open_positions}
        </Fact>
        <Fact label={t("users.seen")} testId="admin-user-seen">
          {dateTimeText(user.last_seen_at, i18n.language)}
        </Fact>
      </dl>
      {user.exchanges_with_no_key.length > 0 && (
        <p data-testid="admin-user-no-key" className="text-sm text-loss">
          {t("users.poolWithNoKey", { exchanges: user.exchanges_with_no_key.join(", ") })}
        </p>
      )}
    </li>
  );
}

function UsersList() {
  const { t } = useTranslation();
  const users = useAdminUsers();
  const me = useMe();

  if (users.status === "pending") return <p className="text-sm text-ink-2">{t("users.loading")}</p>;
  if (users.status === "error") {
    return (
      <p role="alert" className="text-sm text-loss">
        {t("users.error")}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {me.data?.dryRunBrake === true && <p className="text-sm text-ink-2">{t("users.brake")}</p>}
      <ul className="flex flex-col gap-3">
        {users.data.map((user) => (
          <UserRow key={user.email} user={user} />
        ))}
      </ul>
    </div>
  );
}

/**
 * Every user with their state, for the admin (decision 8): enough to support someone and to understand a
 * discrepancy, and no amount and no performance. The mode shown is the one the user chose, so under the brake the
 * page says it is not the one they trade in.
 */
export function UsersPage() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-5">
      <h1 className="font-display text-2xl font-bold text-ink">{t("users.title")}</h1>
      <UsersList />
    </div>
  );
}
