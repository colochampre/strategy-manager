import { useTranslation } from "react-i18next";

import { formatUtcTimestamp } from "@/features/bookings/format";
import type { BookingProposal, ProposedFill } from "@/shared/api/types";

interface BookingCardProps {
  proposal: BookingProposal;
}

/**
 * Renders one PENDING proposal exactly as frozen — every money field is the
 * STRING the backend sent, never re-parsed through `Number`/`parseFloat`,
 * because that would silently lose precision on an append-only ledger's
 * evidence (design.md § 3). No approve/reject action lives here: unit 9b
 * owns the confirm/reject dialogs.
 */
export function BookingCard({ proposal }: BookingCardProps) {
  const { t } = useTranslation();

  return (
    <article className="flex flex-col gap-3 rounded-lg border border-edge bg-surface-900 p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-ink-100">{proposal.symbol}</p>
          <p className="text-xs text-ink-500">
            {proposal.exchange} · {proposal.venue} · {proposal.settlement_currency}
          </p>
        </div>
        <p className="text-xs text-ink-500">
          {t("bookings.card.expires")}: {formatUtcTimestamp(proposal.expires_at)}
        </p>
      </header>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-3">
        <Field label={t("bookings.card.strategy")} value={proposal.strategy_id} />
        <Field label={t("bookings.card.allocation")} value={proposal.allocation_id} />
        <Field label={t("bookings.card.side")} value={proposal.side} />
        <Field label={t("bookings.card.quantity")} value={proposal.quantity} tabular />
        <Field
          label={t("bookings.card.observedVenueNet")}
          value={proposal.observed_venue_net_base}
          tabular
        />
        <Field
          label={t("bookings.card.observedLedgerNet")}
          value={proposal.observed_ledger_net_base}
          tabular
        />
      </dl>

      <div>
        <p className="mb-1 text-xs font-semibold text-ink-300">{t("bookings.card.fills")}</p>
        <ul className="flex flex-col gap-1">
          {proposal.fills.map((fill) => (
            <FillRow key={fill.exchange_fill_id} fill={fill} />
          ))}
        </ul>
      </div>
    </article>
  );
}

interface FieldProps {
  label: string;
  value: string;
  tabular?: boolean;
}

function Field({ label, value, tabular = false }: FieldProps) {
  return (
    <div>
      <dt className="text-ink-500">{label}</dt>
      <dd className={tabular ? "tabular text-ink-100" : "text-ink-100"}>{value}</dd>
    </div>
  );
}

interface FillRowProps {
  fill: ProposedFill;
}

function FillRow({ fill }: FillRowProps) {
  const { t } = useTranslation();

  return (
    <li className="tabular flex flex-wrap gap-x-2 text-xs text-ink-300">
      <span>{fill.side}</span>
      <span>{fill.quantity}</span>
      <span>@ {fill.price}</span>
      <span>
        {t("bookings.card.fee")}: {fill.fee} {fill.fee_currency}
      </span>
      <span>{formatUtcTimestamp(fill.filled_at)}</span>
      <span>#{fill.exchange_fill_id}</span>
    </li>
  );
}
