import { afterAll, beforeAll, describe, expect, it } from "vitest";

import {
  dayTicks,
  drawdownPath,
  gridBand,
  linePath,
  monthTicks,
  sliceAndRebase,
  tickValues,
  timeScale,
  waterlineScale,
  windowStartDate,
} from "./scale";
import type { IndexDay } from "./scale";

const HEIGHT = 280;
const WATER = 0.62;

describe("waterlineScale", () => {
  it("test_waterline_scale_upper_band_takes_62_percent_lower_38_percent", () => {
    const scale = waterlineScale(0.3, 0.1, HEIGHT, WATER);
    expect(scale.waterY).toBeCloseTo(173.6, 6);
    expect(scale.y(0)).toBeCloseTo(173.6, 6);
    // The top of the plot is the upper extreme, the bottom is the lower one.
    expect(scale.y(0.3)).toBeCloseTo(0, 6);
    expect(scale.y(-0.1)).toBeCloseTo(280, 6);
    // Each band is linear inside its own extent.
    expect(scale.y(0.15)).toBeCloseTo(86.8, 6);
    expect(scale.y(-0.05)).toBeCloseTo(173.6 + 106.4 / 2, 6);
  });

  it("test_waterline_scale_each_band_floors_at_10_percent", () => {
    const scale = waterlineScale(0.02, 0.01, HEIGHT, WATER);
    expect(scale.upperMax).toBeCloseTo(0.1, 10);
    expect(scale.lowerMax).toBeCloseTo(0.1, 10);
    // A 2% gain fills a fifth of the upper band, a 1% drawdown a tenth of the lower.
    expect(scale.y(0.02)).toBeCloseTo(173.6 * 0.8, 6);
    expect(scale.y(-0.01)).toBeCloseTo(173.6 + 106.4 * 0.1, 6);
  });

  it("floors each band on its own: a big gain does not stretch the lower band", () => {
    const scale = waterlineScale(0.5, 0.03, HEIGHT, WATER);
    expect(scale.upperMax).toBeCloseTo(0.5, 10);
    expect(scale.lowerMax).toBeCloseTo(0.1, 10);
  });

  it("test_waterline_scale_negative_cumulative_return_crosses_into_lower_band", () => {
    // Nothing above the waterline: the upper band keeps its floor and the
    // negative cumulative return is drawn on the lower band's scale.
    const scale = waterlineScale(0, 0.25, HEIGHT, WATER);
    expect(scale.upperMax).toBeCloseTo(0.1, 10);
    expect(scale.lowerMax).toBeCloseTo(0.25, 10);
    expect(scale.y(-0.25)).toBeCloseTo(280, 6);
    expect(scale.y(-0.125)).toBeCloseTo(173.6 + 53.2, 6);
    expect(scale.y(-0.125)).toBeGreaterThan(scale.waterY);
  });

  it("keeps the waterline defined for a zero-range series", () => {
    const scale = waterlineScale(0, 0, HEIGHT, WATER);
    expect(Number.isFinite(scale.y(0))).toBe(true);
    expect(scale.y(0)).toBeCloseTo(173.6, 6);
  });
});

describe("linePath", () => {
  it("test_line_path_no_smoothing_one_point_per_utc_day", () => {
    const points = [
      { x: 0, y: 10 },
      { x: 10, y: 20.5 },
      { x: 20, y: 5 },
      { x: 30, y: 7.25 },
    ];
    const path = linePath(points);
    expect(path).toBe("M0,10 L10,20.5 L20,5 L30,7.25");
    // One command per point, straight segments only.
    expect(path.match(/[A-Za-z]/g)).toEqual(["M", "L", "L", "L"]);
    expect(path).not.toMatch(/[CQSTA]/);
  });

  it("rounds coordinates to two decimals and never writes exponents or NaN", () => {
    expect(linePath([{ x: 1 / 3, y: 2 / 3 }, { x: 1e-9, y: 100 }])).toBe("M0.33,0.67 L0,100");
  });

  it("is empty for no points and a single move for one point", () => {
    expect(linePath([])).toBe("");
    expect(linePath([{ x: 5, y: 7 }])).toBe("M5,7");
  });
});

describe("drawdownPath", () => {
  it("test_drawdown_path_closed_from_waterline_to_dd", () => {
    const points = [
      { x: 10, y: 170 },
      { x: 20, y: 190 },
      { x: 30, y: 180 },
    ];
    expect(drawdownPath(points, 173.6)).toBe("M10,173.6 L10,170 L20,190 L30,180 L30,173.6 Z");
  });

  it("is empty for an empty series and still closed for a single point", () => {
    expect(drawdownPath([], 100)).toBe("");
    expect(drawdownPath([{ x: 4, y: 120 }], 100)).toBe("M4,100 L4,120 L4,100 Z");
  });
});

describe("monthTicks", () => {
  const originalTz = process.env.TZ;
  beforeAll(() => {
    // A zone far west of UTC: a local-time parse would put the 1st on the 31st.
    process.env.TZ = "America/Los_Angeles";
  });
  afterAll(() => {
    if (originalTz === undefined) delete process.env.TZ;
    else process.env.TZ = originalTz;
  });

  it("test_month_ticks_first_utc_day_of_each_month", () => {
    const dates = ["2026-07-14", "2026-07-31", "2026-08-01", "2026-08-20", "2026-09-01", "2026-09-30"];
    expect(monthTicks(dates)).toEqual([
      { date: "2026-08-01", year: 2026, month: 8 },
      { date: "2026-09-01", year: 2026, month: 9 },
    ]);
  });

  it("crosses a year change", () => {
    const dates = ["2026-11-20", "2026-12-15", "2027-01-10", "2027-02-01"];
    expect(monthTicks(dates)).toEqual([
      { date: "2026-12-01", year: 2026, month: 12 },
      { date: "2027-01-01", year: 2027, month: 1 },
      { date: "2027-02-01", year: 2027, month: 2 },
    ]);
  });

  it("puts a tick on the 1st even when the series has no row that day", () => {
    expect(monthTicks(["2026-03-28", "2026-04-03"])).toEqual([
      { date: "2026-04-01", year: 2026, month: 4 },
    ]);
  });

  it("has no ticks for an empty series, one point, or a span inside one month", () => {
    expect(monthTicks([])).toEqual([]);
    expect(monthTicks(["2026-05-01"])).toEqual([{ date: "2026-05-01", year: 2026, month: 5 }]);
    expect(monthTicks(["2026-05-03", "2026-05-29"])).toEqual([]);
  });
});

describe("timeScale", () => {
  it("places days proportionally in UTC between the two edges", () => {
    const x = timeScale(["2026-01-01", "2026-01-11", "2026-01-31"], 44, 796);
    expect(x("2026-01-01")).toBeCloseTo(44, 6);
    expect(x("2026-01-11")).toBeCloseTo(44 + 752 / 3, 6);
    expect(x("2026-01-31")).toBeCloseTo(796, 6);
  });

  it("centres a single point and tolerates an empty series", () => {
    expect(timeScale(["2026-01-01"], 44, 796)("2026-01-01")).toBeCloseTo(420, 6);
    expect(timeScale([], 44, 796)("2026-01-01")).toBe(44);
  });
});

describe("gridBand", () => {
  it("test_grid_band_zero_boundary_2_5_percent_boundary_15_percent_and_beyond", () => {
    expect(gridBand(0)).toBe(0);
    expect(gridBand(0.0001)).toBe(1);
    expect(gridBand(0.025)).toBe(1);
    expect(gridBand(0.0251)).toBe(2);
    expect(gridBand(0.05)).toBe(2);
    expect(gridBand(0.075)).toBe(3);
    expect(gridBand(0.125)).toBe(5);
    expect(gridBand(0.1251)).toBe(6);
    expect(gridBand(0.15)).toBe(6);
    expect(gridBand(0.3)).toBe(6);
  });

  it("is not thrown a band up by float noise on an exact boundary", () => {
    // 0.025 * 3 is 0.07500000000000001 in binary floating point.
    expect(0.025 * 3).toBeGreaterThan(0.075);
    expect(gridBand(0.025 * 3)).toBe(3);
  });

  it("reads the magnitude, so the sign is the caller's colour choice", () => {
    expect(gridBand(-0.026)).toBe(2);
    expect(gridBand(-0.4)).toBe(6);
  });
});

describe("tickValues", () => {
  it("picks the finest standard step that keeps a band to five lines or fewer", () => {
    expect(tickValues(0.3)).toEqual([0.1, 0.2, 0.3]);
    expect(tickValues(0.1)).toEqual([0.05, 0.1]);
    expect(tickValues(0.12)).toEqual([0.05, 0.1]);
    expect(tickValues(0.6)).toEqual([0.25, 0.5]);
  });

  it("never returns a tick beyond the band", () => {
    expect(tickValues(0.29)).toEqual([0.1, 0.2]);
  });
});

function indexDay(date: string, index: number, drawdown = 0): IndexDay {
  return { date, index, drawdown };
}

describe("windowStartDate", () => {
  const originalTz = process.env.TZ;
  beforeAll(() => {
    process.env.TZ = "America/Los_Angeles";
  });
  afterAll(() => {
    if (originalTz === undefined) delete process.env.TZ;
    else process.env.TZ = originalTz;
  });

  it("is the UTC calendar day N days before now", () => {
    expect(windowStartDate(Date.UTC(2026, 8, 30, 12, 0), 7)).toBe("2026-09-23");
    expect(windowStartDate(Date.UTC(2026, 8, 30, 12, 0), 30)).toBe("2026-08-31");
    expect(windowStartDate(Date.UTC(2026, 8, 30, 12, 0), 365)).toBe("2025-09-30");
  });

  it("reads the UTC day, not the viewer's, just after UTC midnight", () => {
    // 00:30 UTC on the 30th is still the 29th in Los Angeles; the server counts UTC.
    expect(windowStartDate(Date.UTC(2026, 8, 30, 0, 30), 7)).toBe("2026-09-23");
  });
});

describe("sliceAndRebase", () => {
  it("rebases on the last point BEFORE the window, not on its first point inside", () => {
    const days = [
      indexDay("2026-06-20", 1.1),
      indexDay("2026-06-28", 1.21),
      indexDay("2026-06-30", 1.331),
      indexDay("2026-07-02", 1.2),
    ];
    const window = sliceAndRebase(days, "2026-06-29");
    expect(window.map((day) => day.date)).toEqual(["2026-06-30", "2026-07-02"]);
    expect(window[0]!.cumulative).toBeCloseTo(0.1, 10);
    expect(window[1]!.cumulative).toBeCloseTo(1.2 / 1.21 - 1, 10);
  });

  it("starts from an index of 1 when nothing precedes the window", () => {
    const window = sliceAndRebase([indexDay("2026-06-30", 1.05), indexDay("2026-07-02", 1.1)], "2026-06-01");
    expect(window[0]!.cumulative).toBeCloseTo(0.05, 10);
    expect(window[1]!.cumulative).toBeCloseTo(0.1, 10);
  });

  it("includes the start day itself", () => {
    const window = sliceAndRebase([indexDay("2026-06-28", 1.1), indexDay("2026-06-29", 1.21)], "2026-06-29");
    expect(window.map((day) => day.date)).toEqual(["2026-06-29"]);
    expect(window[0]!.cumulative).toBeCloseTo(0.1, 10);
  });

  it("measures the drawdown from the peak INSIDE the window", () => {
    // The pool peaked at 1.5 long before; inside the window its own peak is the start.
    const days = [
      indexDay("2026-06-10", 1.5),
      indexDay("2026-06-28", 1.2, -0.2),
      indexDay("2026-07-01", 1.26, -0.16),
      indexDay("2026-07-02", 1.197, -0.202),
    ];
    const window = sliceAndRebase(days, "2026-06-29");
    expect(window[0]!.drawdown).toBeCloseTo(0, 10);
    expect(window[1]!.drawdown).toBeCloseTo(1.197 / 1.26 - 1, 10);
  });

  it("counts the window's own start as its first peak, like the server's E_0 of 1", () => {
    const window = sliceAndRebase([indexDay("2026-06-28", 1.2), indexDay("2026-07-01", 1.14)], "2026-06-29");
    expect(window[0]!.cumulative).toBeCloseTo(1.14 / 1.2 - 1, 10);
    expect(window[0]!.drawdown).toBeCloseTo(1.14 / 1.2 - 1, 10);
  });

  it("returns the whole series, with the server drawdown, when there is no window", () => {
    const days = [indexDay("2026-06-01", 1.2, -0.01), indexDay("2026-06-02", 1.1, -0.0833)];
    const all = sliceAndRebase(days, null);
    expect(all.map((day) => day.date)).toEqual(["2026-06-01", "2026-06-02"]);
    expect(all[0]!.cumulative).toBeCloseTo(0.2, 10);
    expect(all[1]!.cumulative).toBeCloseTo(0.1, 10);
    expect(all.map((day) => day.drawdown)).toEqual([-0.01, -0.0833]);
  });

  it("is empty when no day falls in the window", () => {
    expect(sliceAndRebase([indexDay("2026-05-01", 1.2)], "2026-06-01")).toEqual([]);
    expect(sliceAndRebase([], "2026-06-01")).toEqual([]);
  });
});

describe("dayTicks", () => {
  const originalTz = process.env.TZ;
  beforeAll(() => {
    process.env.TZ = "America/Los_Angeles";
  });
  afterAll(() => {
    if (originalTz === undefined) delete process.env.TZ;
    else process.env.TZ = originalTz;
  });

  it("lists every UTC day from start to end inclusive at step 1", () => {
    expect(dayTicks("2026-09-28", "2026-10-02", 1)).toEqual([
      "2026-09-28",
      "2026-09-29",
      "2026-09-30",
      "2026-10-01",
      "2026-10-02",
    ]);
  });

  it("steps a week from the start and stops at the end", () => {
    expect(dayTicks("2026-09-01", "2026-09-30", 7)).toEqual([
      "2026-09-01",
      "2026-09-08",
      "2026-09-15",
      "2026-09-22",
      "2026-09-29",
    ]);
  });

  it("has one tick when start equals end and none when end precedes start", () => {
    expect(dayTicks("2026-09-01", "2026-09-01", 1)).toEqual(["2026-09-01"]);
    expect(dayTicks("2026-09-02", "2026-09-01", 1)).toEqual([]);
  });
});

/**
 * The server, ported: each trade returns r_i, same-day returns are SUMMED,
 * days are COMPOUNDED from E_0 = 1 (performance/domain/curve.py). A range is
 * built from the trades inside [now - N days, now] and compounded on its own.
 */
interface Trade {
  closedAt: number;
  ret: number;
}

function dailyReturns(trades: readonly Trade[]): Array<[string, number]> {
  const byDay = new Map<string, number>();
  for (const trade of trades) {
    const day = new Date(trade.closedAt).toISOString().slice(0, 10);
    byDay.set(day, (byDay.get(day) ?? 0) + trade.ret);
  }
  return [...byDay.entries()].sort(([a], [b]) => (a < b ? -1 : 1));
}

function serverCurve(trades: readonly Trade[]): IndexDay[] {
  let index = 1;
  let peak = 1;
  return dailyReturns(trades).map(([date, ret]) => {
    index *= 1 + ret;
    peak = Math.max(peak, index);
    return { date, index, drawdown: index / peak - 1 };
  });
}

function serverRange(trades: readonly Trade[], now: number, days: number): number {
  const start = now - days * 86_400_000;
  const inside = trades.filter((trade) => trade.closedAt >= start && trade.closedAt <= now);
  return dailyReturns(inside).reduce((index, [, ret]) => index * (1 + ret), 1) - 1;
}

describe("the rebased window against the server's ranges", () => {
  const NOW = Date.UTC(2026, 8, 30, 12, 0, 0);
  const RANGE_DAYS = { "7D": 7, "30D": 30, "90D": 90, "1Y": 365 } as const;

  // Deterministic, with gaps, losing streaks and two trades on some days.
  // Every trade closes at exactly 12:00:00 UTC, the same time of day as NOW.
  // ASSUMPTION: that puts the start instant (now - N days) on a boundary of
  // the trades, so no day straddles the window edge. A trade earlier on the
  // edge day than the start instant is dropped by the server's instant window
  // but kept by a window cut on whole UTC days: see the last test here.
  function fixtureTrades(): Trade[] {
    let seed = 12345;
    const rand = () => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed / 2147483648;
    };
    const trades: Trade[] = [];
    for (let back = 500; back >= 0; back -= 1) {
      if (rand() < 0.4) continue;
      const closedAt = NOW - back * 86_400_000;
      trades.push({ closedAt, ret: (rand() - 0.52) * 0.04 });
      if (rand() < 0.3) trades.push({ closedAt, ret: (rand() - 0.5) * 0.02 });
    }
    return trades;
  }

  it.each(Object.entries(RANGE_DAYS))("ends %s on the server's range return", (_name, days) => {
    const trades = fixtureTrades();
    const window = sliceAndRebase(serverCurve(trades), windowStartDate(NOW, days));
    expect(window.length).toBeGreaterThan(0);
    expect(window[window.length - 1]!.cumulative).toBeCloseTo(serverRange(trades, NOW, days), 10);
  });

  it("ends All on the server's All return", () => {
    const trades = fixtureTrades();
    const all = sliceAndRebase(serverCurve(trades), null);
    expect(all[all.length - 1]!.cumulative).toBeCloseTo(serverRange(trades, NOW, 10_000), 10);
  });

  it("differs only by the edge day when a trade precedes the start instant that same day", () => {
    const edgeDay = Date.UTC(2026, 8, 23);
    const trades: Trade[] = [
      { closedAt: edgeDay + 6 * 3_600_000, ret: 0.1 }, // 06:00: before the 12:00 start instant
      { closedAt: edgeDay + 12 * 3_600_000, ret: 0.02 }, // 12:00: inside, at the inclusive start
      { closedAt: NOW, ret: 0.01 },
    ];
    const window = sliceAndRebase(serverCurve(trades), windowStartDate(NOW, 7));
    // The server drops the 06:00 trade; whole-day slicing keeps that day's summed return.
    expect(serverRange(trades, NOW, 7)).toBeCloseTo(1.02 * 1.01 - 1, 10);
    expect(window[window.length - 1]!.cumulative).toBeCloseTo(1.12 * 1.01 - 1, 10);
  });
});
