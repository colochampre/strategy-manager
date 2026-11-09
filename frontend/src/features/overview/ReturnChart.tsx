import { useId, useState } from "react";
import type { PointerEvent, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { RangeName } from "@/features/overview/RangeSelector";
import type { CurvePoint } from "@/shared/api/types";
import {
  dayTicks,
  drawdownPath,
  linePath,
  monthTicks,
  sliceAndRebase,
  spanTicks,
  tickValues,
  timeScale,
  utcDate,
  waterlineScale,
  windowStartDate,
  withOrigin,
} from "@/shared/charts/scale";
import type { IndexDay } from "@/shared/charts/scale";
import { useElementWidth } from "@/shared/charts/useElementWidth";

interface ReturnChartProps {
  /** The pool's whole curve, oldest day first; the range picks the window drawn. */
  curve: readonly CurvePoint[];
  range: RangeName;
  /** The instant the report was read, in ms: the "now" a range window ends on. */
  asOf: number;
  /** Shown at the right of the header, on the title's row: the range selector. */
  headerAction?: ReactNode;
  /** Replaces the Overview's title (already translated), for a chart of one strategy. */
  title?: string;
  /**
   * The UTC day the first trade opened, where the curve starts at 0 (decision 36);
   * `null` or absent draws the curve from its first close.
   */
  origin?: string | null;
  /**
   * A day to mark with a vertical line and its label (already translated): the day a reader's seat began.
   * It is drawn only when the day falls inside the drawn window, from its start to today.
   */
  marker?: ChartMarker | null;
}

export interface ChartMarker {
  /** A UTC `YYYY-MM-DD` day. */
  date: string;
  label: string;
}

/** The marker's label is about this wide; past it the label is written to the line's left. */
const MARKER_LABEL_WIDTH = 120;

/**
 * The drawing is laid out in real pixels: the `viewBox` is the measured width of
 * its box by a FIXED height, so the height never grows with the screen (a wide
 * panel gets a wide chart, not a tall one) and the fonts and strokes stay the
 * size they are written at. `DEFAULT_WIDTH` stands in until the first
 * measurement and wherever nothing measures (jsdom); below `MIN_WIDTH` the plot
 * would be too small to read, so the drawing stops narrowing there.
 */
const DEFAULT_WIDTH = 796;
const MIN_WIDTH = 280;
const VIEW_HEIGHT = 280;
const LEFT = 44;
/** The gap between the plot's right edge and the box's. */
const RIGHT_MARGIN = 6;
const TOP = 12;
const PLOT_HEIGHT = 244;
/** The band above the waterline takes 62% of the plot, the band below 38%. */
const WATER_RATIO = 0.62;
const MONTH_LABEL_Y = 274;
/** Month labels closer than this many units to the previous one are dropped. */
const MIN_LABEL_GAP = 28;
/** The All range's two end labels are written as days, wider than a month: a date between keeps this far from them. */
const END_LABEL_GAP = 40;
/** The hover label is about this wide; past it from the right edge it is written to the guide's left. */
const HOVER_LABEL_WIDTH = 96;
/** The fill under the curve is this opaque at the plot's top and bottom edges, and clear at the waterline. */
const FILL_OPACITY = 0.28;

type TickKind = "day" | "week" | "month";

interface AxisLabel {
  date: string;
  x: number;
  /** A month start is written as its month; every other date as its day. */
  kind: "day" | "month";
}

interface RangeWindow {
  /** The window length in days, as the server counts it; `null` is the whole curve. */
  days: number | null;
  ticks: TickKind;
}

/** `days` is the server's `_RANGE_DAYS`; the ticks are chosen so each window reads at a glance. */
const RANGE_WINDOWS: Readonly<Record<RangeName, RangeWindow>> = {
  "7D": { days: 7, ticks: "day" },
  "30D": { days: 30, ticks: "week" },
  "90D": { days: 90, ticks: "month" },
  "1Y": { days: 365, ticks: "month" },
  All: { days: null, ticks: "month" },
};

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const DECIMAL = /^-?\d+(\.\d+)?$/;

/** Parses the server's strings for geometry only; `null` when any value is unreadable. */
function readCurve(curve: readonly CurvePoint[]): IndexDay[] | null {
  const days: IndexDay[] = [];
  for (const point of curve) {
    if (!DATE.test(point.date) || !DECIMAL.test(point.index) || !DECIMAL.test(point.drawdown)) {
      return null;
    }
    days.push({ date: point.date, index: Number(point.index), drawdown: Number(point.drawdown) });
  }
  return days;
}

const MONTH_FORMAT_OPTIONS: Intl.DateTimeFormatOptions = { month: "short", timeZone: "UTC" };
const DAY_FORMAT_OPTIONS: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", timeZone: "UTC" };

/** `YYYY-MM-DD` as the UTC instant the formatters read in UTC. */
function utcInstant(date: string): Date {
  const [year, month, day] = date.split("-").map(Number);
  return new Date(Date.UTC(year ?? Number.NaN, (month ?? Number.NaN) - 1, day ?? Number.NaN));
}

/** A signed whole-or-half percentage; U+2212 is the minus the design draws. */
function percentLabel(ratio: number): string {
  const magnitude = String(Math.round(Math.abs(ratio) * 1000) / 10);
  if (ratio > 0) return `+${magnitude}%`;
  if (ratio < 0) return `−${magnitude}%`;
  return "0%";
}

export function ReturnChart({
  curve,
  range,
  asOf,
  headerAction = null,
  title,
  origin = null,
  marker = null,
}: ReturnChartProps) {
  const { t, i18n } = useTranslation();
  const [measure, measuredWidth] = useElementWidth<HTMLDivElement>(DEFAULT_WIDTH);
  const gradientId = useId();
  const [hovered, setHovered] = useState<number | null>(null);
  const viewWidth = Math.max(MIN_WIDTH, measuredWidth);
  const right = viewWidth - RIGHT_MARGIN;
  const series = readCurve(curve);
  const rangeWindow = RANGE_WINDOWS[range];
  const from = rangeWindow.days === null ? null : windowStartDate(asOf, rangeWindow.days);
  const days = series === null ? null : withOrigin(sliceAndRebase(series, from), origin, from);

  // The title with its caption beneath on the left, the action (the range selector) on the right:
  // the caption costs no row of its own because the 44 px selector is taller than the two lines.
  const header = (
    <div data-testid="chart-header" className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <div className="flex min-w-0 flex-col">
        <h2 className="font-display text-base font-semibold text-ink">
          {title ?? t("overview.returnChart.title")}
        </h2>
        <span className="font-mono text-[11px] text-ink-3">{t("overview.returnChart.caption")}</span>
      </div>
      {headerAction}
    </div>
  );

  if (days === null) {
    return (
      <figure className="flex flex-col gap-2">
        {header}
        <p role="alert" className="text-sm text-loss">
          {t("overview.returnChart.unreadable")}
        </p>
      </figure>
    );
  }

  const up = Math.max(0, ...days.map((day) => day.cumulative));
  const down = Math.max(0, ...days.map((day) => -Math.min(day.cumulative, day.drawdown)));
  const scale = waterlineScale(up, down, PLOT_HEIGHT, WATER_RATIO);
  const toY = (ratio: number) => TOP + scale.y(ratio);
  const waterY = toY(0);

  // Every range runs to today, so a quiet stretch since the last close shows as empty space; a
  // bounded one also starts on its own window, the whole curve on its first day (its origin).
  const today = utcDate(asOf);
  const start = from ?? days[0]?.date ?? null;
  const domain = start === null ? [] : [start, today];
  const x = timeScale(domain, LEFT, right);
  const curvePoints = days.map((day) => ({ x: x(day.date), y: toY(day.cumulative) }));
  const drawdownPoints = days.map((day) => ({ x: x(day.date), y: toY(day.drawdown) }));

  const upperTicks = days.length === 0 ? [] : tickValues(scale.upperMax);
  const lowerTicks = days.length === 0 ? [] : tickValues(scale.lowerMax);
  // Top to bottom: the upper band, the waterline, the lower band.
  const rows = [
    ...[...upperTicks].reverse().map((value) => ({ value, y: toY(value) })),
    { value: 0, y: waterY },
    ...lowerTicks.map((value) => ({ value: -value, y: toY(-value) })),
  ];

  const locale = i18n.resolvedLanguage ?? "en";
  const dayFormat = new Intl.DateTimeFormat(locale, DAY_FORMAT_OPTIONS);
  const monthFormat = new Intl.DateTimeFormat(locale, MONTH_FORMAT_OPTIONS);
  const labels = from === null ? wholeCurveLabels(start, today) : windowLabels(from, today);

  /** A bounded window: its ticks, each closer than the gap to the previous one dropped. */
  function windowLabels(windowStart: string, end: string): AxisLabel[] {
    const kind = rangeWindow.ticks;
    const dates =
      kind === "month" ? monthTicks(domain).map((tick) => tick.date) : dayTicks(windowStart, end, kind === "day" ? 1 : 7);
    let previousX = Number.NEGATIVE_INFINITY;
    return dates.flatMap((date) => {
      const tickX = x(date);
      if (tickX - previousX < MIN_LABEL_GAP) return [];
      previousX = tickX;
      return [{ date, x: tickX, kind: kind === "month" ? "month" : "day" }];
    });
  }

  /** The All range: its start and today always named, the dates between kept clear of both. */
  function wholeCurveLabels(first: string | null, end: string): AxisLabel[] {
    if (first === null) return [];
    const startX = x(first);
    const endX = x(end);
    const between = spanTicks(first, end);
    const kind = between.kind === "month" ? "month" : "day";
    const inside: AxisLabel[] = [];
    let previousX = startX;
    let gap = END_LABEL_GAP;
    for (const date of between.dates) {
      const tickX = x(date);
      if (tickX - previousX < gap || endX - tickX < END_LABEL_GAP) continue;
      inside.push({ date, x: tickX, kind });
      previousX = tickX;
      gap = MIN_LABEL_GAP;
    }
    const ends: AxisLabel[] = [{ date: first, x: startX, kind: "day" }];
    return first === end ? ends : [...ends, ...inside, { date: end, x: endX, kind: "day" }];
  }

  const emptyMessage =
    series !== null && series.length === 0
      ? t("overview.returnChart.empty")
      : t("overview.returnChart.emptyRange");

  const first = curvePoints[0];

  /** The day nearest the pointer, in drawing units; none while the pointer is off the plot. */
  function hover(event: PointerEvent<SVGSVGElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const unit = box.width > 0 ? viewWidth / box.width : 1;
    const pointerX = (event.clientX - box.left) * unit;
    if (first === undefined || pointerX < LEFT || pointerX > right) {
      setHovered(null);
      return;
    }
    let nearest = 0;
    curvePoints.forEach((candidate, i) => {
      if (Math.abs(candidate.x - pointerX) < Math.abs((curvePoints[nearest]?.x ?? 0) - pointerX)) nearest = i;
    });
    setHovered(nearest);
  }

  const hoveredDay = hovered === null ? undefined : days[hovered];
  const hoveredPoint = hovered === null ? undefined : curvePoints[hovered];
  // ISO dates compare as text. Outside [start, today] there is nothing on the axis to mark.
  const markerShown = marker !== null && start !== null && marker.date >= start && marker.date <= today;
  const markerX = markerShown ? x(marker.date) : 0;

  return (
    <figure className="flex flex-col gap-2">
      {header}
      <div ref={measure} className="min-w-0">
        <svg
          role="img"
          aria-label={t("overview.returnChart.ariaLabel")}
          viewBox={`0 0 ${viewWidth} ${VIEW_HEIGHT}`}
          height={VIEW_HEIGHT}
          className="block w-full touch-pan-y"
          onPointerMove={hover}
          onPointerDown={hover}
          onPointerLeave={() => setHovered(null)}
          onPointerCancel={() => setHovered(null)}
        >
          <defs>
            <linearGradient
              id={gradientId}
              gradientUnits="userSpaceOnUse"
              x1={0}
              x2={0}
              y1={TOP}
              y2={TOP + PLOT_HEIGHT}
              className="text-gain"
            >
              <stop offset={0} stopColor="currentColor" stopOpacity={FILL_OPACITY} />
              <stop offset={WATER_RATIO} stopColor="currentColor" stopOpacity={0} />
              <stop offset={1} stopColor="currentColor" stopOpacity={FILL_OPACITY} />
            </linearGradient>
          </defs>
          {labels.map(({ date, x: tickX }) => (
            <line
              key={date}
              data-testid="vgridline"
              x1={tickX}
              x2={tickX}
              y1={TOP}
              y2={TOP + PLOT_HEIGHT}
              className="stroke-rule-soft"
            />
          ))}
          <g className="fill-ink-3 font-mono text-[10px]">
            {rows.map(({ value, y }) => (
              <g key={value}>
                {value !== 0 && (
                  <line
                    data-testid="gridline"
                    x1={LEFT}
                    x2={viewWidth}
                    y1={y}
                    y2={y}
                    className="stroke-rule-soft"
                  />
                )}
                <text data-testid="y-label" x={0} y={y + 3}>
                  {percentLabel(value)}
                </text>
              </g>
            ))}
          </g>
          <line
            data-testid="waterline"
            x1={LEFT}
            x2={viewWidth}
            y1={waterY}
            y2={waterY}
            strokeWidth={1.5}
            className="stroke-rule-strong"
          />
          {first === undefined ? (
            <text
              x={(LEFT + right) / 2}
              y={waterY - 14}
              textAnchor="middle"
              className="fill-ink-3 font-mono text-[11px]"
            >
              {emptyMessage}
            </text>
          ) : (
            <>
              <path
                data-testid="return-fill"
                d={drawdownPath(curvePoints, waterY)}
                fill={`url(#${gradientId})`}
                className="stroke-none"
              />
              <path
                data-testid="drawdown-fill"
                d={drawdownPath(drawdownPoints, waterY)}
                className="fill-loss/20 stroke-none"
              />
              <path
                data-testid="drawdown-edge"
                d={linePath(drawdownPoints)}
                strokeWidth={1.4}
                className="fill-none stroke-loss"
              />
              <path
                data-testid="return-curve"
                data-final-return={String(days[days.length - 1]?.cumulative ?? 0)}
                d={linePath(curvePoints)}
                strokeWidth={2.2}
                strokeLinejoin="round"
                className="fill-none stroke-gain"
              />
              {curvePoints.length === 1 && (
                <circle data-testid="return-dot" cx={first.x} cy={first.y} r={3} className="fill-gain" />
              )}
            </>
          )}
          {hoveredDay !== undefined && hoveredPoint !== undefined && (
            <g className="pointer-events-none">
              <line
                data-testid="hover-guide"
                x1={hoveredPoint.x}
                x2={hoveredPoint.x}
                y1={TOP}
                y2={TOP + PLOT_HEIGHT}
                strokeWidth={1}
                className="stroke-ink-3"
              />
              <circle
                data-testid="hover-dot"
                cx={hoveredPoint.x}
                cy={hoveredPoint.y}
                r={4}
                strokeWidth={2}
                className="fill-gain stroke-ground"
              />
              <text
                data-testid="hover-label"
                x={hoveredPoint.x > right - HOVER_LABEL_WIDTH ? hoveredPoint.x - 6 : hoveredPoint.x + 6}
                y={TOP + 22}
                textAnchor={hoveredPoint.x > right - HOVER_LABEL_WIDTH ? "end" : "start"}
                paintOrder="stroke"
                strokeWidth={4}
                strokeLinejoin="round"
                className="fill-ink stroke-ground font-mono text-[11px]"
              >
                {`${dayFormat.format(utcInstant(hoveredDay.date))} · ${percentLabel(hoveredDay.cumulative)}`}
              </text>
            </g>
          )}
          {markerShown && (
            <g>
              <line
                data-testid="seat-marker"
                x1={markerX}
                x2={markerX}
                y1={TOP}
                y2={TOP + PLOT_HEIGHT}
                strokeWidth={1.5}
                strokeDasharray="4 3"
                className="stroke-ink-2"
              />
              <text
                x={markerX > right - MARKER_LABEL_WIDTH ? markerX - 4 : markerX + 4}
                y={TOP + 10}
                textAnchor={markerX > right - MARKER_LABEL_WIDTH ? "end" : "start"}
                className="fill-ink-2 font-mono text-[10px]"
              >
                {marker.label}
              </text>
            </g>
          )}
          <g className="fill-ink-3 font-mono text-[10px]">
            {labels.map(({ date, x: tickX, kind }) => (
              <text
                key={date}
                data-testid={kind === "month" ? "month-label" : "day-label"}
                x={tickX}
                y={MONTH_LABEL_Y}
                // A label on the right edge would run past the drawing and be clipped.
                textAnchor={tickX > right - 12 ? "end" : "middle"}
              >
                {(kind === "month" ? monthFormat : dayFormat).format(utcInstant(date))}
              </text>
            ))}
          </g>
        </svg>
      </div>
    </figure>
  );
}
