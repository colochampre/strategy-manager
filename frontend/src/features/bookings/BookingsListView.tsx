import { useState } from "react";
import { useTranslation } from "react-i18next";

import { BookingCard } from "@/features/bookings/BookingCard";
import { ConfirmBookingDialog } from "@/features/bookings/ConfirmBookingDialog";
import { RejectBookingDialog } from "@/features/bookings/RejectBookingDialog";
import { usePendingBookings } from "@/features/bookings/usePendingBookings";
import { ApiError } from "@/shared/api/client";
import type { BookingProposal } from "@/shared/api/types";

interface BookingsListViewProps {
  exchange?: string;
  /** What to say when nothing is pending; defaults to the bookings page's own wording. */
  emptyText?: string;
}

/**
 * Pending-bookings list. With `exchange` set it shows only that exchange's
 * proposals, filtered on the client (owner decision 3): the endpoint has no
 * exchange parameter, and each proposal carries its own `exchange`, the same
 * identifier `GET /pools` reports. Without it every row renders, which is what
 * a caller that has no exchange scope gets. The Overview never omits it while
 * the scope is unresolved, because unfiltered rows under an exchange tab would
 * claim a filter that is not applied.
 *
 * Loading, empty and error are three DISTINCT renders, never confused: an
 * `ApiError` (any status, including a network failure reported as status 0)
 * always shows the error panel with its status/detail, never the empty
 * state. A 401 clears the token store inside `apiFetch` itself, so the
 * enclosing `TokenGate` re-renders its paste-once form on its own -- this
 * view does not special-case it.
 */
export function BookingsListView({ exchange, emptyText }: BookingsListViewProps) {
  const { t } = useTranslation();
  const query = usePendingBookings();
  const [confirmTarget, setConfirmTarget] = useState<BookingProposal | null>(null);
  const [rejectTarget, setRejectTarget] = useState<BookingProposal | null>(null);

  if (query.status === "pending") {
    return (
      <p role="status" className="text-sm text-ink-3">
        {t("bookings.loading")}
      </p>
    );
  }

  if (query.status === "error") {
    const error = query.error;
    const status = error instanceof ApiError ? error.status : undefined;
    const detail = error instanceof ApiError ? error.detail : undefined;
    return (
      <div role="alert" className="rounded-md border border-loss bg-panel p-4 text-sm">
        <p className="font-semibold text-loss">{t("bookings.error.title")}</p>
        {status !== undefined && (
          <p className="mt-1 text-ink-2">{t("bookings.error.status", { status })}</p>
        )}
        {detail !== undefined && <p className="text-ink-2">{detail}</p>}
      </div>
    );
  }

  const proposals =
    exchange === undefined
      ? query.data
      : query.data.filter((proposal) => proposal.exchange === exchange);

  if (proposals.length === 0) {
    return <p className="text-sm text-ink-3">{emptyText ?? t("bookings.empty")}</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      {proposals.map((proposal) => (
        <div key={proposal.id} className="flex flex-col gap-2">
          <BookingCard proposal={proposal} />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setRejectTarget(proposal)}
              className="min-h-11 rounded-md border border-rule px-3 py-1.5 text-xs text-ink-2 hover:bg-panel-2"
            >
              {t("bookings.actions.reject")}
            </button>
            <button
              type="button"
              onClick={() => setConfirmTarget(proposal)}
              className="min-h-11 rounded-md bg-gain px-3 py-1.5 text-xs font-medium text-ground hover:opacity-90"
            >
              {t("bookings.actions.approve")}
            </button>
          </div>
        </div>
      ))}
      {confirmTarget && (
        <ConfirmBookingDialog proposal={confirmTarget} onClose={() => setConfirmTarget(null)} />
      )}
      {rejectTarget && (
        <RejectBookingDialog proposal={rejectTarget} onClose={() => setRejectTarget(null)} />
      )}
    </div>
  );
}
