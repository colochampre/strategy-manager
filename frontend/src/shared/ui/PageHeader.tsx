import { ChevronRight, House } from "lucide-react";
import { Fragment, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

export interface Crumb {
  label: string;
  /** Where it goes; a crumb without one is a heading with no page of its own (Administration). */
  to?: string;
}

/**
 * The trail above a title: the home icon, then each crumb, the last one being the current page. Used by `PageHeader`
 * and, on a strategy page, by the header that holds the title beside the aside.
 */
export function Breadcrumb({ crumbs }: { crumbs: readonly Crumb[] }) {
  const { t } = useTranslation();
  return (
    <nav aria-label={t("nav.breadcrumb")}>
      <ol className="flex flex-wrap items-center gap-2 text-[13px] text-ink-3">
        <li className="flex items-center">
          <Link to="/" aria-label={t("nav.home")} className="inline-flex text-ink-3 hover:text-ink">
            <House aria-hidden="true" className="size-4" />
          </Link>
        </li>
        {crumbs.map((crumb, index) => {
          const last = index === crumbs.length - 1;
          return (
            <Fragment key={`${index}-${crumb.label}`}>
              <li aria-hidden="true" className="flex items-center">
                <ChevronRight className="size-4" />
              </li>
              <li className="flex min-w-0 items-center">
                {crumb.to !== undefined && !last ? (
                  <Link to={crumb.to} className="truncate hover:text-ink">
                    {crumb.label}
                  </Link>
                ) : (
                  <span {...(last ? { "aria-current": "page" as const } : {})} className={last ? "truncate font-medium text-ink-2" : "truncate"}>
                    {crumb.label}
                  </span>
                )}
              </li>
            </Fragment>
          );
        })}
      </ol>
    </nav>
  );
}

interface PageHeaderProps {
  crumbs: readonly Crumb[];
  title: ReactNode;
  subtitle?: ReactNode;
}

/**
 * The header every page opens with (S2): breadcrumb, `h1`, subtitle, in the same spacing everywhere so nothing jumps
 * when navigating. The blocks below it stack 4 apart (L.13), so its own bottom margin of 8 makes the 24 the
 * prototype leaves between the subtitle and the first card.
 */
export function PageHeader({ crumbs, title, subtitle }: PageHeaderProps) {
  return (
    <header className="mb-2 flex flex-col gap-3.5">
      <Breadcrumb crumbs={crumbs} />
      <div className="flex flex-col gap-1.5">
        <h1 className="font-display text-[28px] font-semibold leading-[1.15] tracking-[-0.005em] text-ink">{title}</h1>
        {subtitle !== undefined && <p className="text-ink-2">{subtitle}</p>}
      </div>
    </header>
  );
}
