import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { PageHeader } from "@/shared/ui/PageHeader";

/** Client-side 404: the server already answered index.html for this path. */
export function NotFoundPage() {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col items-start gap-4">
      <PageHeader
        crumbs={[{ label: t("notFound.title") }]}
        title={t("notFound.title")}
        subtitle={t("pageHeader.notFound")}
      />
      <Link to="/" className="text-sm text-gain hover:text-gain-bright">
        {t("notFound.back")}
      </Link>
    </div>
  );
}
