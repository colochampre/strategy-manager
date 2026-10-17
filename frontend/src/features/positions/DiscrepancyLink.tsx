import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { VenueFollowUp } from "@/features/positions/useVenueFollowUp";

interface DiscrepancyLinkProps {
  followUp: VenueFollowUp;
  pair: string;
}

/** "See the discrepancy", a real link named for the pair, to the item on the discrepancies page. */
export function DiscrepancyLink({ followUp, pair }: DiscrepancyLinkProps) {
  const { t } = useTranslation();
  return (
    <Link to={followUp.to} aria-label={t("positions.venue.linkName", { pair })} className="underline underline-offset-4">
      {t("positions.venue.link")}
    </Link>
  );
}
