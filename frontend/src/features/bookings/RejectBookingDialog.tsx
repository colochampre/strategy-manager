import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { outcomeMessageKey } from "@/features/bookings/outcomeMessage";
import { ApiError, apiFetch } from "@/shared/api/client";
import type { BookingProposal, RejectResponse } from "@/shared/api/types";

interface RejectBookingDialogProps {
  proposal: BookingProposal;
  onClose: () => void;
}

/**
 * Submit is refused client-side on an empty or whitespace-only reason; the
 * trimmed reason is what gets sent. The backend's own 422 REASON_REQUIRED
 * is still handled (design.md § 12) in case the two ever disagree.
 */
export function RejectBookingDialog({ proposal, onClose }: RejectBookingDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const reasonId = useId();
  const queryClient = useQueryClient();
  const submittingRef = useRef(false);
  const [reason, setReason] = useState("");
  const [validationError, setValidationError] = useState(false);

  const mutation = useMutation<RejectResponse, Error, string>({
    mutationFn: (trimmedReason) =>
      apiFetch<RejectResponse>(`/reconciliation/bookings/${proposal.id}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: trimmedReason }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["bookings", "pending"] });
    },
    onError: (error) => {
      // Same reasoning as ConfirmBookingDialog: only success and a 409
      // (ALREADY_DECIDED) mean the backend's state actually moved.
      if (error instanceof ApiError && error.status === 409) {
        void queryClient.invalidateQueries({ queryKey: ["bookings", "pending"] });
      }
    },
  });

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = reason.trim();
    if (trimmed.length === 0) {
      setValidationError(true);
      return;
    }
    setValidationError(false);
    if (submittingRef.current) {
      return;
    }
    submittingRef.current = true;
    mutation.mutate(trimmed, {
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
      <form
        onSubmit={handleSubmit}
        className="flex w-full max-w-lg flex-col gap-4 rounded-lg border border-edge bg-surface-900 p-6"
      >
        <h2 id={titleId} className="text-sm font-semibold text-ink-100">
          {t("bookings.dialogs.reject.title")}
        </h2>
        <p className="text-xs text-ink-500">{t("bookings.dialogs.reject.description")}</p>

        {!settled && (
          <div className="flex flex-col gap-1">
            <label htmlFor={reasonId} className="text-xs text-ink-500">
              {t("bookings.dialogs.reject.reasonLabel")}
            </label>
            <textarea
              id={reasonId}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder={t("bookings.dialogs.reject.reasonPlaceholder")}
              disabled={disabled}
              className="min-h-20 rounded-md border border-edge bg-surface-850 px-3 py-2 text-sm text-ink-100 focus:border-accent focus:outline-none disabled:opacity-50"
            />
            {validationError && (
              <p role="alert" className="text-xs text-loss">
                {t("bookings.dialogs.reject.reasonRequired")}
              </p>
            )}
          </div>
        )}

        {mutation.status === "success" && (
          <p role="status" className="text-sm text-profit">
            {t("bookings.dialogs.reject.success")}
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
                type="submit"
                disabled={disabled}
                className="rounded-md bg-loss px-3 py-1.5 text-sm font-medium text-ink-100 hover:opacity-90 disabled:opacity-50"
              >
                {disabled
                  ? t("bookings.dialogs.reject.submitting")
                  : t("bookings.dialogs.reject.confirm")}
              </button>
            </>
          )}
        </div>
      </form>
    </div>
  );
}
