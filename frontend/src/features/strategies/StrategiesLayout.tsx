import { useTranslation } from "react-i18next";
import { Outlet, useLocation } from "react-router";

import { PageHeader } from "@/shared/ui/PageHeader";

/** Which of the three lists the path names. `/strategies` alone is My subscriptions; the others start with their own. */
function listOf(pathname: string): "authored" | "explore" | "subscriptions" {
  if (pathname.startsWith("/strategies/authored")) return "authored";
  if (pathname.startsWith("/strategies/explore")) return "explore";
  return "subscriptions";
}

/**
 * The three lists of Strategies under one header: what the user holds, what is public, and what they wrote. The
 * sidebar's Strategies group replaces the tabs they used to have (S4); each list names itself in the header, below
 * the breadcrumb "Strategies > list".
 */
export function StrategiesLayout() {
  const { t } = useTranslation();
  const list = listOf(useLocation().pathname);
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        crumbs={[{ label: t("nav.strategies") }, { label: t(`nav.${list}`) }]}
        title={t(`nav.${list}`)}
        subtitle={t(`pageHeader.${list}`)}
      />
      <Outlet />
    </div>
  );
}
