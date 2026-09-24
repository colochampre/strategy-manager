import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useRef } from "react";
import { useTranslation } from "react-i18next";

import { formatUtcTimestamp } from "@/features/bookings/format";
import { outcomeMessageKey } from "@/features/bookings/outcomeMessage";
import { ApiError, apiFetch } from "@/shared/api/client";
import type { ApproveResponse, BookingProposal } from "@/shared/api/types";

interface ConfirmBookingDialogProps {
  proposal: BookingProposal;
  onClose: () => void;
}

/**
 * The second confirmation: every row is rendered from the proposal's own
 * FROZEN snapshot, never recomputed client-side (design.md § 12). This
 * dialog's confirm button is the ONLY caller of the approve mutation --
 * nothing else in this component calls `mutation.mutate`. `usd_rate` is
 * deliberately absent from the wire shape; the note below explains why
 * (rule 7).
 */
export function ConfirmBookingDialog({ proposal, onClose }: ConfirmBookingDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const queryClient = useQueryClient();
  const submittingRef = useRef(false);

  const mutation = useMutation<ApproveResponse, Error, void>({
    mutationFn: () =>
      apiFetch<ApproveResponse>(`/reconciliation/bookings/${proposal.id}/approve`, {
        method: "POST",
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["bookings", "pending"] });
    },
    onError: (error) => {
      // Only success and a 409 mean the backend committed a state change
      // (this call's own APPROVED, or someone else's ALREADY_DECIDED /
      // SUPERSEDED / EXPIRED write) -- a 503/404/network failure wrote
      // nothing, so the pending list is still accurate as-is.
      if (error instanceof ApiError && error.status === 409) {
        void queryClient.invalidateQueries({ queryKey: ["bookings", "pending"] });
      }
    },
  });

  const handleConfirm = () => {
    if (submittingRef.current) {
      return;
    }
    submittingRef.current = true;
    mutation.mutate(undefined, {
      onSettled: () => {
        submittingRef.current = false;
      },
    });
  };

  const disabled = mutation.isPending;
  const settled = mutation.status === "success";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      className="fixed inset-0 z-50 flex items-center justify-center bg-surface-950/80 p-4"
    >
      <div className="flex w-full max-w-lg flex-col gap-4 rounded-lg border border-edge bg-surface-900 p-6">
        <h2 id={titleId} className="text-sm font-semibold text-ink-100">
          {t("bookings.dialogs.confirm.title")}
        </h2>
        <p className="text-xs text-ink-500">{t("bookings.dialogs.confirm.description")}</p>

        <div>
          <p className="mb-1 text-xs font-semibold text-ink-300">{t("bookings.card.fills")}</p>
          <ul className="flex flex-col gap-1">
            {proposal.fills.map((fill) => (
              <li
                key={fill.exchange_fill_id}
                className="tabular flex flex-wrap gap-x-2 text-xs text-ink-300"
              >
                <span>{fill.side}</span>
                <span>{fill.quantity}</span>
                <span>@ {fill.price}</span>
                <span>
                  {t("bookings.card.fee")}: {fill.fee} {fill.fee_currency}
                </span>
                <span>{formatUtcTimestamp(fill.filled_at)}</span>
                <span>#{fill.exchange_fill_id}</span>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <p className="mb-1 text-xs font-semibold text-ink-300">{t("bookings.dialogs.attempt.heading")}</p>
          <div className="tabular flex flex-wrap gap-x-2 text-xs text-ink-300">
            <span>{t("bookings.dialogs.attempt.origin")}=VENUE</span>
            <span>{t("bookings.dialogs.attempt.status")}=FILLED</span>
            <span>{proposal.client_order_id}</span>
            <span>{proposal.allocation_id}</span>
            <span>{proposal.strategy_id}</span>
          </div>
        </div>

        <p className="text-xs text-ink-500">{t("bookings.dialogs.confirm.usdRateNote")}</p>

        {mutation.status === "success" && (
          <p role="status" className="text-sm text-profit">
            {t("bookings.dialogs.confirm.success")}
          </p>
        )}

        {mutation.status === "error" && (
          <p role="alert" className="text-sm text-loss">
            {t(outcomeMessageKey(mutation.error))}
          </p>
        )}

        <div className="flex justify-end gap-2">
          {settled ? (
            <button
              type="button"
              onClick={onClose}
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-ink-100 hover:opacity-90"
            >
              {t("bookings.dialogs.close")}
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={onClose}
                disabled={disabled}
                className="rounded-md border border-edge px-3 py-1.5 text-sm text-ink-300 hover:bg-surface-850 disabled:opacity-50"
              >
                {t("bookings.dialogs.cancel")}
              </button>
              <button
                type="button"
                onClick={handleConfirm}
                disabled={disabled}
                className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-ink-100 hover:opacity-90 disabled:opacity-50"
              >
                {disabled
                  ? t("bookings.dialogs.confirm.submitting")
                  : t("bookings.dialogs.confirm.confirm")}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
