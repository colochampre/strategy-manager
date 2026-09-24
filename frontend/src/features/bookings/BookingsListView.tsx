import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { BookingCard } from "@/features/bookings/BookingCard";
import { ApiError, apiFetch } from "@/shared/api/client";
import type { BookingProposal } from "@/shared/api/types";

async function fetchPendingBookings(): Promise<BookingProposal[]> {
  return apiFetch<BookingProposal[]>("/reconciliation/bookings?state=pending");
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
        <BookingCard key={proposal.id} proposal={proposal} />
      ))}
    </div>
  );
}
