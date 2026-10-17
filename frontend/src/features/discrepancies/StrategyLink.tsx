import { useTranslation } from "react-i18next";
import { Link } from "react-router";

interface StrategyLinkProps {
  id: string | null;
  name: string | null;
}

/**
 * A strategy's name as a link to its page (`/strategies/:id`). A strategy whose row is missing has no name and
 * reads "unknown strategy" (K row 13); a name with no id is text, not a link to nothing.
 */
export function StrategyLink({ id, name }: StrategyLinkProps) {
  const { t } = useTranslation();
  if (name === null) return <>{t("discrepancies.label.unknownStrategy")}</>;
  if (id === null) return <>{name}</>;
  return (
    <Link to={`/strategies/${id}`} className="text-gain hover:text-gain-bright">
      {name}
    </Link>
  );
}
