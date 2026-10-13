import { Fragment } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ORIGIN_STYLE } from "@/features/positions/origin";
import type { Origin } from "@/features/positions/origin";
import { OriginTag } from "@/features/positions/OriginTag";
import { cn } from "@/shared/lib/cn";

export type MarkOrigin = Origin;

export type MarkProps =
  | { kind: "position"; origin: MarkOrigin; pair: string; side: "LONG" | "SHORT" | null }
  | { kind: "order"; origin: MarkOrigin; pair: string }
  | { kind: "venue" };

/**
 * The chip's base, common to every variant: mono, 12 px on a 16 px line, 2 px by 8 px of padding, a 4 px
 * radius, a 1 px border and one line. Below `lg` a chip may break anywhere, so a long pair cannot push the
 * row wider than a phone.
 */
const BASE =
  "inline-flex max-w-full font-mono text-xs leading-4 px-2 py-0.5 border rounded-sm whitespace-nowrap max-lg:whitespace-normal max-lg:break-all";

/** The separator inside a mark, in the faint ink. */
function Separator() {
  return <span className="whitespace-pre text-ink-3"> · </span>;
}

function Parts({ parts }: { parts: ReactNode[] }) {
  return (
    <>
      {parts.map((part, index) => (
        <Fragment key={index}>
          {index > 0 && <Separator />}
          {part}
        </Fragment>
      ))}
    </>
  );
}

/**
 * One chip of the shape-and-colour rule (design § H): filled with a solid border is a position; unfilled with
 * a dashed border is an order in flight, and dashed means nothing else; the border and the word repeat the
 * origin's token, which `origin.ts` owns; red is the venue chip and a position of both origins, always with
 * its words. LONG and SHORT stay in ink, because a side is not a result.
 */
export function Mark(props: MarkProps) {
  const { t } = useTranslation();

  if (props.kind === "venue") {
    return <span className={cn(BASE, "border-loss bg-transparent text-loss")}>{t("positions.venue.disagrees")}</span>;
  }

  const border = ORIGIN_STYLE[props.origin].border;
  if (props.kind === "order") {
    return (
      <span className={cn(BASE, "border-dashed bg-transparent text-ink", border)}>
        <Parts parts={[props.pair, t("positions.order.inFlight"), <OriginTag key="origin" origin={props.origin} />]} />
      </span>
    );
  }

  const side = props.side === null ? t("positions.sideUnreadable") : props.side;
  return (
    <span className={cn(BASE, "bg-panel-2 text-ink", border)}>
      <Parts parts={[props.pair, <span key="side">{side}</span>, <OriginTag key="origin" origin={props.origin} />]} />
    </span>
  );
}
