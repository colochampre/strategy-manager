import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { ORIGIN_STYLE } from "@/features/positions/origin";
import { OPEN_POSITIONS_KEY, notShown, useOpenPositions } from "@/shared/api/positions";
import type { InFlightOrder, OpenPosition, OpenState } from "@/shared/api/positions";
import { cn } from "@/shared/lib/cn";
import { timeOfAnswerText } from "@/shared/lib/figure-text";

interface OpenStateLineProps {
  /** The selected tab's exchange. */
  exchange: string;
  /** The ids of the rows on screen, or null while the strategies list is loading. */
  visibleStrategyIds: ReadonlySet<string> | null;
}

const SEPARATOR = " · ";

type Translate = ReturnType<typeof useTranslation>["t"];

function join(parts: ReadonlyArray<string | null>): string {
  return parts.filter((part): part is string => part !== null).join(SEPARATOR);
}

/** "name · archived · pair · origin · figures not readable", the item of a position the list does not show. */
function positionItem(position: OpenPosition, t: Translate): string {
  return join([
    position.strategy_name,
    position.strategy_archived === true ? t("positions.state.archived") : null,
    position.markets.join(" / "),
    t(ORIGIN_STYLE[position.origin].textKey),
    position.figures_missing === null ? null : t("positions.state.unreadable"),
  ]);
}

/**
 * The item of an order: the same parts with "order in flight" before the origin. An order whose
 * `strategy_name` is null (its parent rows are missing, a stored-data fault) has no name to put first, so
 * its item is the order's own mark text, `{market} · order in flight · {origin}` (N3).
 */
function orderItem(order: InFlightOrder, t: Translate): string {
  return join([
    order.strategy_name,
    order.strategy_name !== null && order.strategy_archived === true ? t("positions.state.archived") : null,
    order.market,
    t("positions.order.inFlight"),
    t(ORIGIN_STYLE[order.origin].textKey),
  ]);
}

interface FigureProps {
  label: string;
  value: string;
  first?: boolean;
}

/** A label in the faint ink with its colon, and its value; a ` · ` before it unless it starts a line. */
function Figure({ label, value, first = false }: FigureProps) {
  return (
    <div
      className={cn(
        "flex gap-1.5",
        // Below sm the figures wrap and no separator is drawn, so that none starts a line.
        !first && "sm:before:mr-0.5 sm:before:text-ink-3 sm:before:content-['·']",
      )}
    >
      <dt className="text-ink-3">{label}:</dt>
      <dd>{value}</dd>
    </div>
  );
}

const FIGURES = "tabular flex flex-wrap gap-x-4 gap-y-0.5 font-mono text-xs text-ink-2 sm:gap-x-2";

/**
 * The three labelled figures of the Strategies page and the lines under them (design § H, "The summary").
 * It names no exchange. A failed first read draws no figure at all, so a failure is never read as zero open;
 * a failed refresh keeps the last figures and says since when.
 */
export function OpenStateLine({ exchange: _exchange, visibleStrategyIds }: OpenStateLineProps) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const open = useOpenPositions();
  const locale = i18n.resolvedLanguage ?? "en";
  const refresh = (
    <button
      type="button"
      onClick={() => void queryClient.invalidateQueries({ queryKey: OPEN_POSITIONS_KEY })}
      className="min-h-11 flex-none rounded-md border border-rule px-4 text-sm text-ink hover:bg-panel-2"
    >
      {t("positions.state.refresh")}
    </button>
  );

  const held = open.data;
  if (held === undefined) {
    if (open.status === "error") {
      return (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <p role="alert" className="min-w-0 flex-1 basis-96 text-sm text-loss">
            {t("positions.state.error")}
          </p>
          {refresh}
        </div>
      );
    }
    return (
      <p role="status" className="text-sm text-ink-3">
        {t("positions.state.loading")}
      </p>
    );
  }

  const scoped: OpenState = held;
  const named = visibleStrategyIds === null ? null : notShown(scoped, visibleStrategyIds);
  const items =
    named === null
      ? []
      : [...named.positions.map((position) => positionItem(position, t)), ...named.orders.map((order) => orderItem(order, t))];
  const lastRead = timeOfAnswerText(held.as_of, held.as_of, locale, true) ?? held.as_of;
  const stale = open.status === "error";

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <div className="flex min-w-0 flex-1 basis-96 flex-wrap items-start gap-x-2 gap-y-1 text-sm text-ink-2">
        <div role="status" className="flex min-w-0 flex-col gap-1">
          <dl className={FIGURES}>
            <Figure first label={t("positions.state.figures.open")} value={String(scoped.positions.length)} />
            <Figure label={t("positions.state.figures.orders")} value={String(scoped.orders.length)} />
          </dl>
          {items.length > 0 && <p>{t("positions.state.notShown", { items: items.join("; ") })}</p>}
          {stale && <p className="text-loss">{t("positions.state.stale", { time: lastRead })}</p>}
        </div>
        <dl className={FIGURES}>
          <Figure label={t("positions.state.figures.lastRead")} value={t("positions.state.figures.time", { time: lastRead })} />
        </dl>
      </div>
      {refresh}
    </div>
  );
}
