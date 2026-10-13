import { Fragment } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { usePendingBookings } from "@/features/bookings/usePendingBookings";
import { ORIGIN_STYLE } from "@/features/positions/origin";
import type { Origin } from "@/features/positions/origin";
import { OriginTag } from "@/features/positions/OriginTag";
import { pendingProposalNames } from "@/features/positions/pendingProposal";
import type { InFlightOrder, OpenPosition } from "@/shared/api/positions";
import { cn } from "@/shared/lib/cn";
import { figureText, timeOfAnswerText } from "@/shared/lib/figure-text";

export type MarkLineProps =
  | { variant: "order"; origin: Origin; parts: ReactNode[] }
  | { variant: "venue"; name: string; parts: ReactNode[] };

/**
 * The ONE base of the two lines under a position (design addendum § H, "One component for the two lines"): the
 * full width of its container, wrapping, 8 px by 12 px of padding, a 6 px radius, a 1 px border, a transparent
 * fill, mono 12 px, left-aligned, in ink. Both lines are made from it, so that they cannot drift apart; what
 * differs is only the border's style and colour.
 */
const BASE =
  "flex w-full min-w-0 flex-wrap items-center gap-y-0.5 rounded-md border bg-transparent px-3 py-2 text-left font-mono text-xs text-ink";

/** The separator between two parts, in the faint ink. */
function Separator() {
  return <span className="whitespace-pre text-ink-3"> · </span>;
}

/**
 * Exactly two variants. An order in flight is DASHED, in its origin's colour as on a chip (dashed means an
 * order and nothing else); the venue line is SOLID red and is a group with an accessible name. A part that is
 * null is left out, with its separator.
 */
export function MarkLine(props: MarkLineProps) {
  const parts = props.parts.filter((part): part is Exclude<ReactNode, null> => part !== null);
  const content = parts.map((part, index) => (
    <Fragment key={index}>
      {index > 0 && <Separator />}
      {part}
    </Fragment>
  ));

  if (props.variant === "venue") {
    return (
      <div role="group" aria-label={props.name} className={cn(BASE, "border-solid border-loss")}>
        {content}
      </div>
    );
  }
  return <div className={cn(BASE, "border-dashed", ORIGIN_STYLE[props.origin].border)}>{content}</div>;
}

interface OrderLineProps {
  order: InFlightOrder;
  /** The answer's `as_of`: the day a time is compared with. */
  asOf: string;
}

/** An order in flight: pair, "order in flight", opening or closing, the origin, and when it was sent. */
export function OrderLine({ order, asOf }: OrderLineProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? "en";
  const sentAt = order.submitted_at === null ? null : timeOfAnswerText(order.submitted_at, asOf, locale, false);
  return (
    <MarkLine
      variant="order"
      origin={order.origin}
      parts={[
        order.market,
        t("positions.order.inFlight"),
        order.action === null ? null : t(order.action === "OPEN" ? "positions.order.open" : "positions.order.close"),
        <OriginTag key="origin" origin={order.origin} />,
        sentAt === null ? null : t("positions.order.sent", { time: sentAt }),
      ]}
    />
  );
}

interface VenueLineProps {
  position: OpenPosition;
  asOf: string;
}

/**
 * A net as the position stores it, followed by the position's base currency when it has one. A string that is
 * not a plain decimal is "figures not readable", never drawn as typed and never a zero.
 */
function netText(net: string, baseCurrency: string | null, unreadable: string): string {
  const figure = figureText(net) ?? unreadable;
  return baseCurrency === null ? figure : `${figure} ${baseCurrency}`;
}

/**
 * The venue mark as ONE line under its row: pair, "venue disagrees" in red, both nets, when it was last
 * compared, how many positions share the difference (only above one), then the link to the pending decision
 * or the words that no booking is proposed. The pending bookings are asked for only by a position the venue
 * disagrees on; until they are READ neither the link nor the words is drawn (a link would be a guess and the
 * words a claim nobody checked, design § K row 22). A position without a disagreement draws no line.
 */
export function VenueLine({ position, asOf }: VenueLineProps) {
  const { t, i18n } = useTranslation();
  const pending = usePendingBookings();
  const disagreement = position.venue_disagreement;
  if (disagreement === null) return null;

  const locale = i18n.resolvedLanguage ?? "en";
  const pair = position.markets.join(" / ");
  const unreadable = t("positions.state.unreadable");
  const comparedAt = timeOfAnswerText(disagreement.last_observed_at, asOf, locale, true);

  let followUp: ReactNode = null;
  if (pending.data !== undefined) {
    const named = pendingProposalNames(pending.data, position.allocation_id, disagreement.discrepancy_id);
    followUp = named ? (
      <Link
        to={{ pathname: "/", hash: "#decision-rail" }}
        aria-label={t("positions.venue.linkName", { pair })}
        className="underline underline-offset-4"
      >
        {t("positions.venue.link")}
      </Link>
    ) : (
      t("positions.venue.line.noProposal")
    );
  }

  return (
    <MarkLine
      variant="venue"
      name={t("positions.venue.groupName", { pair })}
      parts={[
        pair,
        <span key="disagrees" className="text-loss">
          {t("positions.venue.line.disagrees")}
        </span>,
        t("positions.venue.line.nets", {
          venue: netText(disagreement.venue_net_base, position.base_currency, unreadable),
          ledger: netText(disagreement.ledger_net_base, position.base_currency, unreadable),
        }),
        comparedAt === null ? null : t("positions.venue.line.compared", { time: comparedAt }),
        disagreement.allocation_count > 1 ? t("positions.venue.line.shared", { positions: disagreement.allocation_count }) : null,
        followUp,
      ]}
    />
  );
}
