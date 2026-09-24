import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { BookingCard } from "@/features/bookings/BookingCard";
import { ConfirmBookingDialog } from "@/features/bookings/ConfirmBookingDialog";
import { RejectBookingDialog } from "@/features/bookings/RejectBookingDialog";
import { ApiError, apiFetch } from "@/shared/api/client";
import type { BookingProposal } from "@/shared/api/types";

async function fetchPendingBookings(): Promise<BookingProposal[]> {
  const body = await apiFetch<unknown>("/reconciliation/bookings?state=pending");
  // Never trust a 200's body shape -- a malformed payload (e.g. `{items:
  // []}` instead of a bare array) must render as the error state, never as
  // "no pending bookings" (carried forward from the unit 9a review).
  if (!Array.isArray(body)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /reconciliation/bookings: expected an array",
    });
  }
  return body as BookingProposal[];
}

/**
 * Loading, empty and error are three DISTINCT renders, never confused: an
 * `ApiError` (any status, including a network failure reported as status 0)
 * always shows the error panel with its status/detail, never the empty
 * state. A 401 clears the token store inside `apiFetch` itself, so the
 * enclosing `TokenGate` re-renders its paste-once form on its own -- this
 * view does not special-case it.
 */
export function BookingsListView() {
  const { t } = useTranslation();
  const query = useQuery({
    queryKey: ["bookings", "pending"],
    queryFn: fetchPendingBookings,
  });
  const [confirmTarget, setConfirmTarget] = useState<BookingProposal | null>(null);
  const [rejectTarget, setRejectTarget] = useState<BookingProposal | null>(null);

  if (query.status === "pending") {
    return (
      <p role="status" className="text-sm text-ink-500">
        {t("bookings.loading")}
      </p>
    );
  }

  if (query.status === "error") {
    const error = query.error;
    const status = error instanceof ApiError ? error.status : undefined;
    const detail = error instanceof ApiError ? error.detail : undefined;
    return (
      <div role="alert" className="rounded-md border border-loss bg-surface-900 p-4 text-sm">
        <p className="font-semibold text-loss">{t("bookings.error.title")}</p>
        {status !== undefined && (
          <p className="mt-1 text-ink-300">{t("bookings.error.status", { status })}</p>
        )}
        {detail !== undefined && <p className="text-ink-300">{detail}</p>}
      </div>
    );
  }

  const proposals = query.data;

  if (proposals.length === 0) {
    return <p className="text-sm text-ink-500">{t("bookings.empty")}</p>;
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
              className="rounded-md border border-edge px-3 py-1.5 text-xs text-ink-300 hover:bg-surface-850"
            >
              {t("bookings.actions.reject")}
            </button>
            <button
              type="button"
              onClick={() => setConfirmTarget(proposal)}
              className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-ink-100 hover:opacity-90"
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
