import type { ReactNode } from "react";
import { Search } from "lucide-react";
import { useTranslation } from "react-i18next";

/** Lower case with the accents taken off, so "acido" finds "Ácido". */
function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
}

/** True when `query`, trimmed, is any part of `name`, ignoring case and accents; an empty query matches every name. */
export function matchesName(name: string, query: string): boolean {
  const wanted = fold(query.trim());
  return wanted === "" || fold(name).includes(wanted);
}

interface StrategySearchProps {
  value: string;
  onChange: (value: string) => void;
}

/** The name filter of the Strategies lists, as tall as the buttons beside it. */
export function StrategySearch({ value, onChange }: StrategySearchProps) {
  const { t } = useTranslation();
  return (
    <div className="relative w-full sm:max-w-sm sm:flex-1">
      <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" />
      <input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-label={t("strategies.search.label")}
        placeholder={t("strategies.search.placeholder")}
        className="min-h-11 w-full rounded-md border border-rule bg-panel pr-3 pl-9 text-sm text-ink placeholder:text-ink-3 focus-visible:border-gain focus-visible:outline-none"
      />
    </div>
  );
}

/**
 * One row above every Strategies list: the name search on the left, the list's own buttons on the right. Every list
 * draws it, buttons or not, so switching lists moves nothing. On a phone the search takes its own row above them.
 */
export function ListToolbar({ search, children = null }: { search: ReactNode; children?: ReactNode }) {
  return (
    <div data-testid="list-toolbar" className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      {search}
      {children !== null && <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2">{children}</div>}
    </div>
  );
}

/** The no-match line, naming what was typed. */
export function NoMatch({ query }: { query: string }) {
  const { t } = useTranslation();
  return <p className="text-sm text-ink-3">{t("strategies.search.noMatch", { query: query.trim() })}</p>;
}
