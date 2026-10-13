import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { OPEN_POSITIONS_KEY } from "@/shared/api/positions";
import { cn } from "@/shared/lib/cn";

interface OpenReadStateProps {
  /** The `status` of the open-positions query while it holds no answer. */
  status: "pending" | "error" | "success";
  /** The `errorUpdateCount` of the same query: above zero once a read has failed, and it stays so. */
  errorUpdateCount: number;
}

/**
 * What the open-positions panels draw while the query holds no answer: the loading text on a first load, the
 * error with "Read again" after a failed read, and the loading text beside the SAME button while it reads
 * again.
 *
 * A query with no data goes back to `status: "pending"` the moment it refetches, so `status` alone would take
 * the button away under the finger that pressed it. `errorUpdateCount` is only ever incremented, by a failed
 * read, so above zero it tells "reading again after a failure" from a first load. The button stays mounted in
 * the same place, keeps the focus and is marked `aria-disabled` (never `disabled`, which drops the focus);
 * pressing it meanwhile does nothing, because invalidating would cancel the read in flight and start another.
 */
export function OpenReadState({ status, errorUpdateCount }: OpenReadStateProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const failed = status === "error";
  const reading = !failed && errorUpdateCount > 0;

  if (!failed && !reading) {
    return (
      <p role="status" className="text-sm text-ink-3">
        {t("positions.state.loading")}
      </p>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <p
        role={failed ? "alert" : "status"}
        className={cn("min-w-0 flex-1 basis-96 text-sm", failed ? "text-loss" : "text-ink-3")}
      >
        {failed ? t("positions.state.error") : t("positions.state.loading")}
      </p>
      <button
        type="button"
        aria-disabled={reading ? "true" : undefined}
        onClick={() => {
          if (reading) return;
          void queryClient.invalidateQueries({ queryKey: OPEN_POSITIONS_KEY });
        }}
        className="min-h-11 flex-none rounded-md border border-rule px-4 text-sm text-ink hover:bg-panel-2 aria-disabled:opacity-60"
      >
        {t("positions.state.refresh")}
      </button>
    </div>
  );
}
