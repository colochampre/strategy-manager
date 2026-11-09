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

/**
 * The slope of the curve at each point, by Fritsch-Carlson (what d3 calls
 * `curveMonotoneX`). A point between a rise and a fall, or beside a flat run, gets a
 * level tangent; any other gets the weighted harmonic mean of its two secants,
 * which never exceeds three times the smaller one. So the curve never leaves the band between two
 * neighbours: it can show no high or low that the data does not hold.
 */
function tangents(points: readonly Point[]): number[] {
  const count = points.length;
  const secants: number[] = [];
  for (let i = 0; i < count - 1; i += 1) {
    const a = points[i]!;
    const b = points[i + 1]!;
    const dx = b.x - a.x;
    secants.push(dx > 0 ? (b.y - a.y) / dx : 0);
  }
  const result: number[] = [];
  for (let i = 0; i < count; i += 1) {
    const before = secants[i - 1];
    const after = secants[i];
    if (before === undefined || after === undefined) {
      // An end follows its only secant, which keeps its segment inside its two points.
      result.push(before ?? after ?? 0);
    } else if (before * after <= 0) {
      result.push(0);
    } else {
      const wide = points[i + 1]!.x - points[i - 1]!.x;
      const left = points[i]!.x - points[i - 1]!.x;
      const right = points[i + 1]!.x - points[i]!.x;
      const mean = (3 * wide) / ((wide + right) / before + (wide + left) / after);
      result.push(mean);
    }
  }
  return result;
}

/** One cubic segment from `index - 1` to `index`, its control points a third of the gap along each tangent. */
function segment(points: readonly Point[], slopes: readonly number[], index: number): string {
  const a = points[index - 1]!;
  const b = points[index]!;
  const dx = b.x - a.x;
  // Two points on one x have no horizontal run to curve over.
  if (dx <= 0) return `L${pair(b)}`;
  const first = { x: a.x + dx / 3, y: a.y + (slopes[index - 1]! * dx) / 3 };
  const second = { x: b.x - dx / 3, y: b.y - (slopes[index]! * dx) / 3 };
  return `C${pair(first)} ${pair(second)} ${pair(b)}`;
}

/**
 * A smooth curve through every point: monotone cubic segments, so it passes through each
 * real value and, between two neighbours, never rises above the higher or falls below the
 * lower (smoothing that overshot would invent a high or a low that did not happen).
 */
export function linePath(points: readonly Point[]): string {
  const first = points[0];
  if (first === undefined) return "";
  const slopes = tangents(points);
  const rest = points.slice(1).map((_, i) => segment(points, slopes, i + 1));
  return [`M${pair(first)}`, ...rest].join(" ");
}

/**
 * A closed shape from the waterline, down (or up) along the (smoothed) series, and back to
 * the waterline at the last x.
 */
export function drawdownPath(points: readonly Point[], waterY: number): string {
  const first = points[0];
  const last = points[points.length - 1];
  if (first === undefined || last === undefined) return "";
  const edge = (x: number) => pair({ x, y: waterY });
  const slopes = tangents(points);
  const rest = points.slice(1).map((_, i) => segment(points, slopes, i + 1));
  return [`M${edge(first.x)}`, `L${pair(first)}`, ...rest, `L${edge(last.x)}`, "Z"].join(" ");
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

/** One day of the server's curve, parsed: the compounded index and the server's own drawdown. */
export interface IndexDay {
  date: string;
  index: number;
  drawdown: number;
}

/** One day as the chart draws it: cumulative return (index - 1) and drawdown, both ratios. */
export interface ReturnDay {
  date: string;
  cumulative: number;
  drawdown: number;
}

const DAY_MS = 86_400_000;

/** The UTC calendar date (`YYYY-MM-DD`) of an instant, whatever the viewer's time zone. */
export function utcDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/**
 * The UTC calendar day a window of `days` days ending `nowMs` starts on, the day
 * of the server's instant `now - days`. A curve point is a whole UTC day, so a
 * point belongs to the window when its date is on or after this one.
 */
export function windowStartDate(nowMs: number, days: number): string {
  return utcDate(nowMs - days * DAY_MS);
}

/**
 * The days on or after `from`, rebased so the window starts at zero: each index
 * is divided by the last index BEFORE the window (1 when none precedes it, the
 * server's E_0), and the drawdown is measured from the running peak inside the
 * window, which starts at that rebased 1. An index of zero stays at zero
 * (decision 31), so a window that starts there has nothing to rebase on and reads
 * flat. `from === null` is the whole series, kept exactly as the server wrote it.
 * Ratio arithmetic for display only.
 */
export function sliceAndRebase(days: readonly IndexDay[], from: string | null): ReturnDay[] {
  if (from === null) {
    return days.map((day) => ({ date: day.date, cumulative: day.index - 1, drawdown: day.drawdown }));
  }
  const start = utcDay(from);
  let base = 1;
  const inside: IndexDay[] = [];
  for (const day of days) {
    if (utcDay(day.date) < start) base = day.index;
    else inside.push(day);
  }
  let peak = 1;
  return inside.map((day) => {
    const rebased = base === 0 ? 1 : day.index / base;
    peak = Math.max(peak, rebased);
    return { date: day.date, cumulative: rebased - 1, drawdown: rebased / peak - 1 };
  });
}

/**
 * Decision 36: the curve starts at 0 on `origin`, the UTC day its first trade
 * opened, before the first close. Only where the drawn days reach back to it:
 * the whole curve, or a window starting on or before it (that window has no day
 * before it, so its base is the server's E_0 = 1 and 0 is exact). A window that
 * starts later, and a curve with no close, are left as they are.
 */
export function withOrigin(
  days: readonly ReturnDay[],
  origin: string | null,
  from: string | null,
): ReturnDay[] {
  const first = days[0];
  if (origin === null || first === undefined) return [...days];
  if (from !== null && utcDay(origin) < utcDay(from)) return [...days];
  if (utcDay(origin) > utcDay(first.date)) return [...days];
  return [{ date: origin, cumulative: 0, drawdown: 0 }, ...days];
}

export interface SpanTicks {
  /** How the dates are stepped, which decides how they are written. */
  kind: "day" | "week" | "month";
  /** The dates strictly between the two ends, oldest first. */
  dates: string[];
}

/** Spans up to this many days are labelled every day, up to `WEEK_SPAN_DAYS` every week. */
const DAY_SPAN_DAYS = 14;
const WEEK_SPAN_DAYS = 90;

/**
 * The labels between the two ends of the All range, which carry labels of their
 * own: every day of a span of two weeks or less, every seventh day from the
 * start up to three months, and month starts beyond.
 */
export function spanTicks(start: string, end: string): SpanTicks {
  const spanDays = (utcDay(end) - utcDay(start)) / DAY_MS;
  const inside = (dates: string[]) => dates.filter((date) => date !== start && date !== end);
  if (spanDays <= DAY_SPAN_DAYS) return { kind: "day", dates: inside(dayTicks(start, end, 1)) };
  if (spanDays <= WEEK_SPAN_DAYS) return { kind: "week", dates: inside(dayTicks(start, end, 7)) };
  return { kind: "month", dates: inside(monthTicks([start, end]).map((tick) => tick.date)) };
}

/** Every `step`-th UTC day from `start` while it does not pass `end`. */
export function dayTicks(start: string, end: string, step: number): string[] {
  const last = utcDay(end);
  const ticks: string[] = [];
  for (let day = utcDay(start); day <= last; day += step * DAY_MS) ticks.push(utcDate(day));
  return ticks;
}
