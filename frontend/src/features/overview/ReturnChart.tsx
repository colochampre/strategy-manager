import { useTranslation } from "react-i18next";

import type { CurvePoint } from "@/shared/api/types";
import {
  drawdownPath,
  linePath,
  monthTicks,
  tickValues,
  timeScale,
  waterlineScale,
} from "@/shared/charts/scale";

interface ReturnChartProps {
  /** The pool's whole curve, oldest day first: the chart always shows All. */
  curve: readonly CurvePoint[];
}

/**
 * The drawing is laid out in a fixed box and scaled by the browser through the
 * `viewBox`, so nothing is measured (which is why it is not recharts). Below
 * `MIN_WIDTH` the box scrolls sideways rather than shrinking the ticks to dust.
 */
const VIEW_WIDTH = 796;
const VIEW_HEIGHT = 330;
const LEFT = 44;
const RIGHT = 790;
const TOP = 16;
const PLOT_HEIGHT = 288;
/** The band above the waterline takes 62% of the plot, the band below 38%. */
const WATER_RATIO = 0.62;
const MONTH_LABEL_Y = 322;
/** Month labels closer than this many units to the previous one are dropped. */
const MIN_LABEL_GAP = 28;

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const DECIMAL = /^-?\d+(\.\d+)?$/;

interface Day {
  date: string;
  /** Cumulative return, E - 1. */
  cumulative: number;
  /** Drawdown from the previous peak, at most 0. */
  drawdown: number;
}

/** Parses the server's strings for geometry only; `null` when any value is unreadable. */
function readCurve(curve: readonly CurvePoint[]): Day[] | null {
  const days: Day[] = [];
  for (const point of curve) {
    if (!DATE.test(point.date) || !DECIMAL.test(point.index) || !DECIMAL.test(point.drawdown)) {
      return null;
    }
    days.push({
      date: point.date,
      cumulative: Number(point.index) - 1,
      drawdown: Number(point.drawdown),
    });
  }
  return days;
}

const MONTH_FORMAT_OPTIONS: Intl.DateTimeFormatOptions = { month: "short", timeZone: "UTC" };

/** A signed whole-or-half percentage; U+2212 is the minus the design draws. */
function percentLabel(ratio: number): string {
  const magnitude = String(Math.round(Math.abs(ratio) * 1000) / 10);
  if (ratio > 0) return `+${magnitude}%`;
  if (ratio < 0) return `−${magnitude}%`;
  return "0%";
}

export function ReturnChart({ curve }: ReturnChartProps) {
  const { t, i18n } = useTranslation();
  const days = readCurve(curve);

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

  const x = timeScale(
    days.map((day) => day.date),
    LEFT,
    RIGHT,
  );
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

  const month = new Intl.DateTimeFormat(i18n.resolvedLanguage ?? "en", MONTH_FORMAT_OPTIONS);
  let previousX = Number.NEGATIVE_INFINITY;
  const labels = monthTicks(days.map((day) => day.date)).flatMap((tick) => {
    const tickX = x(tick.date);
    if (tickX - previousX < MIN_LABEL_GAP) return [];
    previousX = tickX;
    return [{ tick, x: tickX }];
  });

  const first = curvePoints[0];

  return (
    <figure className="flex flex-col gap-3">
      {header}
      <div className="overflow-x-auto">
        <svg
          role="img"
          aria-label={t("overview.returnChart.ariaLabel")}
          viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
          preserveAspectRatio="xMidYMid meet"
          className="block h-auto w-full min-w-[560px]"
        >
          <g className="fill-ink-3 font-mono text-[10px]">
            {rows.map(({ value, y }) => (
              <g key={value}>
                {value !== 0 && (
                  <line
                    data-testid="gridline"
                    x1={LEFT}
                    x2={VIEW_WIDTH}
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
            x2={VIEW_WIDTH}
            y1={waterY}
            y2={waterY}
            strokeWidth={1.5}
            className="stroke-rule-strong"
          />
          {first === undefined ? (
            <text
              x={(LEFT + RIGHT) / 2}
              y={waterY - 14}
              textAnchor="middle"
              className="fill-ink-3 font-mono text-[11px]"
            >
              {t("overview.returnChart.empty")}
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
            {labels.map(({ tick, x: tickX }) => (
              <text
                key={tick.date}
                data-testid="month-label"
                x={tickX}
                y={MONTH_LABEL_Y}
                textAnchor="middle"
              >
                {month.format(new Date(Date.UTC(tick.year, tick.month - 1, 1)))}
              </text>
            ))}
          </g>
        </svg>
      </div>
    </figure>
  );
}
