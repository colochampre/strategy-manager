import { useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { CONFIRMED_KEY } from "@/shared/api/discrepancies";
import { cn } from "@/shared/lib/cn";
import { clockSecondsText } from "@/shared/lib/figure-text";

const BUTTON =
  "inline-flex min-h-11 flex-none items-center gap-1.5 rounded-md border border-rule px-4 text-sm text-ink hover:bg-panel-2 aria-disabled:opacity-60";

function useReadAgain() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: CONFIRMED_KEY });
}

interface ReadStateProps {
  /** The `status` of the query while it holds no answer. */
  status: "pending" | "error" | "success";
  /** The `errorUpdateCount` of the same query: above zero once a read has failed, and it stays so. */
  errorUpdateCount: number;
}

/**
 * What the page draws while the query holds no answer: "Reading discrepancies…" on a first load, the error with
 * "Read again" after a failed read, and the loading text beside the SAME button while it reads again. It draws
 * no list and no all-clear in any of the three: a page that could not read cannot say that nothing needs the
 * owner (K row 8).
 *
 * A query with no data goes back to `status: "pending"` the moment it refetches, so `status` alone would take
 * the button away under the finger that pressed it. `errorUpdateCount` only ever grows, by a failed read, so
 * above zero it tells "reading again after a failure" from a first load. The button stays mounted, keeps the
 * focus, and is marked `aria-disabled` (never `disabled`, which drops the focus) while it reads.
 */
export function ReadState({ status, errorUpdateCount }: ReadStateProps) {
  const { t } = useTranslation();
  const readAgain = useReadAgain();
  const failed = status === "error";
  const reading = !failed && errorUpdateCount > 0;

  if (!failed && !reading) {
    return (
      <p role="status" className="text-sm text-ink-3">
        {t("discrepancies.read.loading")}
      </p>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <p
        role={failed ? "alert" : "status"}
        className={cn("min-w-0 flex-1 basis-96 text-sm", failed ? "text-loss" : "text-ink-3")}
      >
        {failed ? t("discrepancies.read.failed") : t("discrepancies.read.loading")}
      </p>
      <button
        type="button"
        aria-disabled={reading ? "true" : undefined}
        onClick={() => {
          if (!reading) readAgain();
        }}
        className={BUTTON}
      >
        <RefreshCw aria-hidden="true" className="size-4 shrink-0" />
        {t("discrepancies.read.refresh")}
      </button>
    </div>
  );
}

interface ReadLineProps {
  /** The `read_at` of the answer the page holds. */
  readAt: string;
  /** A refresh failed: the last answer stays, and the line says since when it could not be refreshed. */
  stale: boolean;
}

/**
 * "Last read {time} UTC" and "Read again". After a failed refresh the last answer stays and the line turns to
 * `loss`, with the time it could not be refreshed since (the time of the answer it still holds).
 */
export function ReadLine({ readAt, stale }: ReadLineProps) {
  const { t } = useTranslation();
  const readAgain = useReadAgain();
  const time = clockSecondsText(readAt) ?? readAt;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <div role="status" className="flex min-w-0 flex-1 basis-96 flex-col gap-1 text-sm">
        <dl className={cn("flex gap-1.5 font-mono text-xs", stale ? "text-loss" : "text-ink-2")}>
          <dt className={cn(stale ? "text-loss" : "text-ink-3")}>{t("discrepancies.read.lastRead")}</dt>
          <dd className={cn(stale && "text-loss")}>{t("discrepancies.read.time", { time })}</dd>
        </dl>
        {stale && <p className="text-loss">{t("discrepancies.read.stale", { time })}</p>}
      </div>
      <button type="button" onClick={readAgain} className={BUTTON}>
        <RefreshCw aria-hidden="true" className="size-4 shrink-0" />
        {t("discrepancies.read.refresh")}
      </button>
    </div>
  );
}
