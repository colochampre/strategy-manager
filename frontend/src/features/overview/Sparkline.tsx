import { useId } from "react";

import type { CurvePoint } from "@/shared/api/types";
import { linePath, sliceAndRebase, utcDate, windowStartDate, withOrigin } from "@/shared/charts/scale";
import type { IndexDay, Point } from "@/shared/charts/scale";

/** The drawing is the prototype's `viewBox="0 0 340 76"`; it stretches to the box it sits in. */
const WIDTH = 340;
const HEIGHT = 76;
/** Room above and below the line so its stroke is never cut. */
const PAD_TOP = 10;
const PAD_BOTTOM = 8;
const DAY_MS = 86_400_000;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const DECIMAL = /^-?\d+(\.\d+)?$/;

interface SparklineProps {
  /** The pool's whole curve, oldest day first. */
  curve: readonly CurvePoint[];
  /** The UTC day the first trade opened, where the curve starts at 0; as `ReturnChart` takes it. */
  origin: string | null;
  /** The instant the report was read, in ms: the "now" the window ends on. */
  asOf: number;
  /** The window in days (30: the card's "last 30 days"). */
  days: number;
}

/** The day's UTC midnight in ms; `null` for text that is not a day. */
function dayMs(date: string): number | null {
  return DATE.test(date) ? Date.parse(`${date}T00:00:00Z`) : null;
}

/**
 * The prototype's sparkline (ex1 `.hc`, 30 days): the return of the last `days` days, rebased to 0 at the window's
 * start, as the compounded-return chart draws that same window, with no axis and no tooltip. It is decorative: the
 * return it stands for is written beside it. A quiet window is a flat line at 0. Geometry only; nothing is summed.
 */
export function Sparkline({ curve, origin, asOf, days }: SparklineProps) {
  const gradientId = useId();
  const series: IndexDay[] = [];
  for (const point of curve) {
    if (!DATE.test(point.date) || !DECIMAL.test(point.index) || !DECIMAL.test(point.drawdown)) return null;
    series.push({ date: point.date, index: Number(point.index), drawdown: Number(point.drawdown) });
  }

  const from = windowStartDate(asOf, days);
  const startMs = dayMs(from);
  const endMs = dayMs(utcDate(asOf));
  if (startMs === null || endMs === null) return null;
  const span = Math.max(endMs - startMs, DAY_MS);

  const drawn = withOrigin(sliceAndRebase(series, from), origin, from);
  const values = [{ ms: startMs, value: 0 }];
  for (const day of drawn) {
    const ms = dayMs(day.date);
    if (ms !== null && ms > startMs) values.push({ ms, value: day.cumulative });
  }
  const last = values[values.length - 1];
  if (last !== undefined && last.ms < endMs) values.push({ ms: endMs, value: last.value });

  const lows = values.map((entry) => entry.value);
  const top = Math.max(0, ...lows);
  const bottom = Math.min(0, ...lows);
  const range = top - bottom;
  const plot = HEIGHT - PAD_TOP - PAD_BOTTOM;
  const toY = (value: number) => (range === 0 ? PAD_TOP + plot / 2 : PAD_TOP + ((top - value) / range) * plot);
  const points: Point[] = values.map((entry) => ({
    x: Math.min(WIDTH, Math.max(0, ((entry.ms - startMs) / span) * WIDTH)),
    y: toY(entry.value),
  }));
  const line = linePath(points);
  const firstPoint = points[0];
  const lastPoint = points[points.length - 1];
  if (firstPoint === undefined || lastPoint === undefined) return null;
  const area = `${line} L ${lastPoint.x},${HEIGHT} L ${firstPoint.x},${HEIGHT} Z`;

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      className="block h-14 w-full md:h-[76px]"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1" className="text-gain">
          <stop offset="0" stopColor="currentColor" stopOpacity={0.3} />
          <stop offset="1" stopColor="currentColor" stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradientId})`} className="stroke-none" />
      <path
        d={line}
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
        className="fill-none stroke-gain"
      />
    </svg>
  );
}
