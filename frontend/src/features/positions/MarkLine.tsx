import type { ReactNode } from "react";

import type { Origin } from "@/features/positions/origin";
import type { InFlightOrder, OpenPosition } from "@/shared/api/positions";

export type MarkLineProps =
  | { variant: "order"; origin: Origin; parts: ReactNode[] }
  | { variant: "venue"; name: string; parts: ReactNode[] };

/** STUB (op.3.1): answers wrongly on purpose. The real line is written in op.3.3. */
export function MarkLine({ parts }: MarkLineProps) {
  return <div>{parts}</div>;
}

interface OrderLineProps {
  order: InFlightOrder;
  /** The answer's `as_of`: the day a time is compared with. */
  asOf: string;
}

export function OrderLine({ order }: OrderLineProps) {
  return <MarkLine variant="order" origin={order.origin} parts={[order.market]} />;
}

interface VenueLineProps {
  position: OpenPosition;
  asOf: string;
}

export function VenueLine({ position }: VenueLineProps) {
  return <MarkLine variant="venue" name={position.markets.join(" / ")} parts={[position.markets.join(" / ")]} />;
}
