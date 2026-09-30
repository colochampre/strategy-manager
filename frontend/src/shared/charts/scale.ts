/**
 * Pure chart geometry: no DOM, no React. Every date is a UTC calendar date
 * (`YYYY-MM-DD`, as the performance endpoint writes it) and is parsed with
 * `Date.UTC`, so the viewer's time zone can never move a day or a month edge.
 *
 * The inputs are ratios (0.05 is 5%) already parsed from the server's strings.
 * This module turns ratios into coordinates and colour bands; it never adds up
 * money.
 */

export interface Point {
  x: number;
  y: number;
}

export interface WaterlineScale {
  /** The y coordinate of 0%: zero cumulative return and zero drawdown at once. */
  waterY: number;
  /** The ratio at the very top of the upper band (at least the floor). */
  upperMax: number;
  /** The ratio, as a magnitude, at the very bottom of the lower band. */
  lowerMax: number;
  /** Positive ratios map into the upper band, negative ones into the lower. */
  y: (value: number) => number;
}

export interface MonthTick {
  /** The first day of the month, `YYYY-MM-01`. */
  date: string;
  year: number;
  /** 1 to 12. */
  month: number;
}

/** A small drawdown must never look catastrophic, so neither band zooms below 10%. */
const BAND_FLOOR = 0.1;

/** The mapping is piecewise linear: each band has its own scale around the waterline. */
export function waterlineScale(
  up: number,
  down: number,
  height: number,
  waterRatio: number,
): WaterlineScale {
  const upperMax = Math.max(up, BAND_FLOOR);
  const lowerMax = Math.max(down, BAND_FLOOR);
  const waterY = height * waterRatio;
  const lowerHeight = height - waterY;
  return {
    waterY,
    upperMax,
    lowerMax,
    y: (value) =>
      value >= 0
        ? waterY - (value / upperMax) * waterY
        : waterY + (-value / lowerMax) * lowerHeight,
  };
}

function coordinate(value: number): string {
  // Two decimals are far below a pixel; `+ 0` folds a negative zero into zero.
  return String(Math.round(value * 100) / 100 + 0);
}

function pair(point: Point): string {
  return `${coordinate(point.x)},${coordinate(point.y)}`;
}

/** Straight segments, one vertex per point: smoothing would invent values. */
export function linePath(points: readonly Point[]): string {
  return points.map((point, i) => `${i === 0 ? "M" : "L"}${pair(point)}`).join(" ");
}

/**
 * A closed shape from the waterline, down (or up) along the series, and back to
 * the waterline at the last x.
 */
export function drawdownPath(points: readonly Point[], waterY: number): string {
  const first = points[0];
  const last = points[points.length - 1];
  if (first === undefined || last === undefined) return "";
  const edge = (x: number) => pair({ x, y: waterY });
  return `M${edge(first.x)} ${points.map((point) => `L${pair(point)}`).join(" ")} L${edge(last.x)} Z`;
}

function utcDay(date: string): number {
  const [year, month, day] = date.split("-").map(Number);
  return Date.UTC(year ?? Number.NaN, (month ?? Number.NaN) - 1, day ?? Number.NaN);
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** The first UTC day of every month that falls inside the series' span. */
export function monthTicks(dates: readonly string[]): MonthTick[] {
  if (dates.length === 0) return [];
  const days = dates.map(utcDay);
  const start = Math.min(...days);
  const end = Math.max(...days);
  const first = new Date(start);
  let year = first.getUTCFullYear();
  let month = first.getUTCMonth();
  // The first of the start month is at or before the span; step to the first inside it.
  if (Date.UTC(year, month, 1) < start) {
    month += 1;
    if (month === 12) {
      month = 0;
      year += 1;
    }
  }
  const ticks: MonthTick[] = [];
  while (Date.UTC(year, month, 1) <= end) {
    ticks.push({ date: `${year}-${pad(month + 1)}-01`, year, month: month + 1 });
    month += 1;
    if (month === 12) {
      month = 0;
      year += 1;
    }
  }
  return ticks;
}

/** Maps a date to x, linearly in UTC time between the series' first and last day. */
export function timeScale(
  dates: readonly string[],
  left: number,
  right: number,
): (date: string) => number {
  if (dates.length === 0) return () => left;
  const days = dates.map(utcDay);
  const start = Math.min(...days);
  const span = Math.max(...days) - start;
  if (span === 0) return () => (left + right) / 2;
  return (date) => left + ((utcDay(date) - start) / span) * (right - left);
}

/** Six bands of 2.5 points on a fixed ±15% scale; 0 is exactly zero, 6 is 12.5% and beyond. */
export function gridBand(value: number): number {
  // Round away the float noise so a month of exactly 7.5% is band 3, not band 4.
  const steps = Number((Math.abs(value) / 0.025).toFixed(9));
  return Math.min(6, Math.ceil(steps));
}

const TICK_STEPS = [0.05, 0.1, 0.25, 0.5];
const COARSEST_STEP = 1;

/** The finest standard step that keeps one band at five gridlines or fewer. */
export function tickValues(max: number): number[] {
  const step = TICK_STEPS.find((candidate) => max / candidate <= 5) ?? COARSEST_STEP;
  const ticks: number[] = [];
  for (let k = 1; k * step <= max + 1e-9; k += 1) {
    ticks.push(Number((k * step).toFixed(10)));
  }
  return ticks;
}
