import { useTranslation } from "react-i18next";
import { Link } from "react-router";

/** Client-side 404: the server already answered index.html for this path. */
export function NotFoundPage() {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col items-start gap-3">
      <h1 className="font-display text-2xl font-bold text-ink">{t("notFound.title")}</h1>
      <Link to="/" className="text-sm text-gain hover:text-gain-bright">
        {t("notFound.back")}
      </Link>
    </div>
  );
}
