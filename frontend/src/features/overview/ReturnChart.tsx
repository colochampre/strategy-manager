import { useTranslation } from "react-i18next";

import type { RangeName } from "@/features/overview/RangeSelector";
import type { CurvePoint } from "@/shared/api/types";
import {
  dayTicks,
  drawdownPath,
  linePath,
  monthTicks,
  sliceAndRebase,
  tickValues,
  timeScale,
  utcDate,
  waterlineScale,
  windowStartDate,
} from "@/shared/charts/scale";
import type { IndexDay } from "@/shared/charts/scale";
import { useElementWidth } from "@/shared/charts/useElementWidth";

interface ReturnChartProps {
  /** The pool's whole curve, oldest day first; the range picks the window drawn. */
  curve: readonly CurvePoint[];
  range: RangeName;
  /** The instant the report was read, in ms: the "now" a range window ends on. */
  asOf: number;
}

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

type TickKind = "day" | "week" | "month";

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

export function ReturnChart({ curve, range, asOf }: ReturnChartProps) {
  const { t, i18n } = useTranslation();
  const [measure, measuredWidth] = useElementWidth<HTMLDivElement>(DEFAULT_WIDTH);
  const viewWidth = Math.max(MIN_WIDTH, measuredWidth);
  const right = viewWidth - RIGHT_MARGIN;
  const series = readCurve(curve);
  const rangeWindow = RANGE_WINDOWS[range];
  const from = rangeWindow.days === null ? null : windowStartDate(asOf, rangeWindow.days);
  const days = series === null ? null : sliceAndRebase(series, from);

  const header = (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4">
      <h2 className="font-display text-base font-semibold text-ink">
        {t("overview.returnChart.title")}
      </h2>
      <span className="font-mono text-[11px] text-ink-3">{t("overview.returnChart.caption")}</span>
    </div>
  );

  if (days === null) {
    return (
      <figure className="flex flex-col gap-3">
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

  // A bounded range runs on its own window, so a quiet stretch at either end shows as empty space.
  const domain = from === null ? days.map((day) => day.date) : [from, utcDate(asOf)];
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
  const axisFormat = new Intl.DateTimeFormat(
    locale,
    rangeWindow.ticks === "month" ? MONTH_FORMAT_OPTIONS : DAY_FORMAT_OPTIONS,
  );
  const tickDates =
    rangeWindow.ticks === "month"
      ? monthTicks(domain).map((tick) => tick.date)
      : from === null
        ? []
        : dayTicks(from, utcDate(asOf), rangeWindow.ticks === "day" ? 1 : 7);
  let previousX = Number.NEGATIVE_INFINITY;
  const labels = tickDates.flatMap((date) => {
    const tickX = x(date);
    if (tickX - previousX < MIN_LABEL_GAP) return [];
    previousX = tickX;
    return [{ date, x: tickX }];
  });
  const labelTestId = rangeWindow.ticks === "month" ? "month-label" : "day-label";
  const emptyMessage =
    series !== null && series.length === 0
      ? t("overview.returnChart.empty")
      : t("overview.returnChart.emptyRange");

  const first = curvePoints[0];

  return (
    <figure className="flex flex-col gap-3">
      {header}
      <div ref={measure} className="min-w-0">
        <svg
          role="img"
          aria-label={t("overview.returnChart.ariaLabel")}
          viewBox={`0 0 ${viewWidth} ${VIEW_HEIGHT}`}
          height={VIEW_HEIGHT}
          className="block w-full"
        >
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
          <g className="fill-ink-3 font-mono text-[10px]">
            {labels.map(({ date, x: tickX }) => (
              <text
                key={date}
                data-testid={labelTestId}
                x={tickX}
                y={MONTH_LABEL_Y}
                // A label on the right edge would run past the drawing and be clipped.
                textAnchor={tickX > right - 12 ? "end" : "middle"}
              >
                {axisFormat.format(utcInstant(date))}
              </text>
            ))}
          </g>
        </svg>
      </div>
    </figure>
  );
}
