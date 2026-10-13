import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { usePendingBookings } from "@/features/bookings/usePendingBookings";
import { Mark } from "@/features/positions/Mark";
import { ofExchange, ofStrategy, useOpenPositions } from "@/shared/api/positions";
import type { OpenPosition, OpenState } from "@/shared/api/positions";
import type { Strategy } from "@/shared/api/types";

interface OpenMarksProps {
  strategy: Strategy;
}

/**
 * From `lg` the marks are the row's second grid row, in the first track only, so the row's figures and its
 * switch stay where they are when the chips wrap; below `lg` they are the row's last full-width line.
 */
const LAYOUT = "flex min-w-0 basis-full flex-wrap items-center gap-1.5 lg:col-start-1 lg:row-start-2 lg:mt-2 lg:basis-auto";

interface VenueNoteProps {
  position: OpenPosition;
  discrepancyId: string;
}

/**
 * The venue chip and what follows it. The pending bookings are asked for only by a position the venue
 * disagrees on. Until they are READ the chip stands alone: a link would be a guess and "no booking is
 * proposed" a claim nobody checked (design § K row 22), so a read that is loading or failed draws neither.
 * The match is the allocation inside its pool and the discrepancy, both as the server sends them.
 */
function VenueNote({ position, discrepancyId }: VenueNoteProps) {
  const { t } = useTranslation();
  const pending = usePendingBookings();
  const pair = position.markets.join(" / ");

  let after: ReactNode = null;
  if (pending.data !== undefined) {
    const named = pending.data.some(
      (proposal) =>
        proposal.state === "PENDING" && proposal.allocation_id === position.allocation_id && proposal.discrepancy_id === discrepancyId,
    );
    after = named ? (
      <Link
        to={{ pathname: "/", hash: "#decision-rail" }}
        aria-label={t("positions.venue.linkName", { pair })}
        className="underline underline-offset-4"
      >
        {t("positions.venue.link")}
      </Link>
    ) : (
      t("positions.venue.noProposal")
    );
  }

  return (
    <>
      <Mark kind="venue" />
      {after !== null && <span className="text-xs text-ink-2">{after}</span>}
    </>
  );
}

/**
 * One chip per position and per order of a strategy. It does not read `strategy.enabled`: a disabled
 * strategy that holds a position shows it like any other. While the answer loads the row draws a decorative
 * ellipsis with the translated text as its name; when the first read failed it draws nothing, and the line
 * above the list says why a row without a mark means nothing. Nothing at all when the strategy holds nothing.
 */
export function OpenMarks({ strategy }: OpenMarksProps) {
  const { t } = useTranslation();
  const open = useOpenPositions();

  if (open.data === undefined) {
    if (open.status === "error") return null;
    return (
      <ul className={LAYOUT}>
        <li className="text-ink-3">
          <span aria-hidden="true">…</span>
          <span className="sr-only">{t("positions.state.loading")}</span>
        </li>
      </ul>
    );
  }

  // A row is on screen only when its strategy's exchange is the selected one, so this is the page's own
  // selection written from what the row has. Never `ofStrategy` alone: a strategy's position whose pool names
  // another exchange (a stored fault) belongs to that exchange's tab, not to this row.
  const mine: OpenState = ofStrategy(ofExchange(open.data, strategy.exchange), strategy.id);
  if (mine.positions.length === 0 && mine.orders.length === 0) return null;

  return (
    <ul aria-label={t("positions.marks.name", { name: strategy.name })} className={LAYOUT}>
      {mine.positions.map((position) => (
        <li
          key={position.allocation_id}
          className={position.venue_disagreement === null ? undefined : "flex max-w-full flex-wrap items-center gap-x-2 gap-y-1.5"}
        >
          <Mark kind="position" origin={position.origin} pair={position.markets.join(" / ")} side={position.side} />
          {position.venue_disagreement !== null && <VenueNote position={position} discrepancyId={position.venue_disagreement.discrepancy_id} />}
        </li>
      ))}
      {mine.orders.map((order) => (
        <li key={order.attempt_id}>
          <Mark kind="order" origin={order.origin} pair={order.market} />
        </li>
      ))}
    </ul>
  );
}
