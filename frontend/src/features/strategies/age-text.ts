import type { TFunction } from "i18next";

const DAY_MS = 86_400_000;

export interface AgeParts {
  years: number;
  months: number;
  days: number;
}

/** `from` moved forward by whole calendar months, in UTC, onto the last day of a shorter month when it must. */
function plusMonths(from: Date, months: number): Date {
  const year = from.getUTCFullYear();
  const month = from.getUTCMonth() + months;
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  return new Date(
    Date.UTC(
      year,
      month,
      Math.min(from.getUTCDate(), lastDay),
      from.getUTCHours(),
      from.getUTCMinutes(),
      from.getUTCSeconds(),
      from.getUTCMilliseconds(),
    ),
  );
}

/**
 * Whole calendar years, months and days from `from` to `to`, read in UTC. Only whole units count: one hour short
 * of a month is 30 days, not a month. A `from` after `to` reads as nothing yet, never as a negative age.
 */
export function ageParts(from: Date, to: Date): AgeParts {
  if (from.getTime() >= to.getTime()) return { years: 0, months: 0, days: 0 };
  let months = (to.getUTCFullYear() - from.getUTCFullYear()) * 12 + (to.getUTCMonth() - from.getUTCMonth());
  if (plusMonths(from, months).getTime() > to.getTime()) months -= 1;
  const days = Math.floor((to.getTime() - plusMonths(from, months).getTime()) / DAY_MS);
  return { years: Math.floor(months / 12), months: months % 12, days };
}

/**
 * An age in its two largest units, short: "6d", "4mo 12d", "1y 4mo". A zero second unit is left out ("1mo",
 * "2y"), and days are dropped once there are years.
 */
export function ageText(t: TFunction, { years, months, days }: AgeParts): string {
  const y = () => t("strategies.age.years", { count: years });
  const mo = () => t("strategies.age.months", { count: months });
  const d = () => t("strategies.age.days", { count: days });
  if (years > 0) return months > 0 ? `${y()} ${mo()}` : y();
  if (months > 0) return days > 0 ? `${mo()} ${d()}` : mo();
  return d();
}
