import { useTranslation } from "react-i18next";

import type { Strategy } from "@/shared/api/types";
import { amountText, parseDecimal } from "@/shared/lib/amount-text";

interface AuthorCapitalProps {
  strategy: Strategy;
  className: string;
}

/**
 * What a strategy holds, for its author: the one figure the public list shows, private strategies included
 * (decisions 10 and 30). Under the server's brake nobody trades live and there is nothing to claim.
 */
export function AuthorCapital({ strategy, className }: AuthorCapitalProps) {
  const { t, i18n } = useTranslation();
  const capital = strategy.capital === null ? null : parseDecimal(strategy.capital);
  if (capital === null) return null;
  const currency = strategy.settlement_currency;
  return (
    <p data-testid="strategy-capital" className={className}>
      {t("strategies.row.capital", { amount: amountText(capital, currency, i18n.language), currency })}
    </p>
  );
}
