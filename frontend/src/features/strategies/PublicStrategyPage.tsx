import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import { PublicFigures, PublicOrigin } from "@/features/strategies/PublicFigures";
import { SubscribePanel } from "@/features/strategies/SubscribePanel";
import { ApiError } from "@/shared/api/client";
import { usePublicStrategy } from "@/shared/api/public-strategies";
import type { PublicStrategy } from "@/shared/api/types";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";

function BackToExplore() {
  const { t } = useTranslation();
  return (
    <Link to="/strategies/explore" className="font-mono text-xs text-ink-3 hover:text-ink-2">
      <span aria-hidden="true">← </span>
      {t("strategies.public.back")}
    </Link>
  );
}

function PublicRecord({ strategy }: { strategy: PublicStrategy }) {
  const { t } = useTranslation();
  const returnInfo = useInfoDisclosure();
  const capitalInfo = useInfoDisclosure();
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1.5">
        <BackToExplore />
        <h1 className="font-display text-2xl font-bold text-ink">{strategy.name}</h1>
        <PublicOrigin strategy={strategy} />
      </header>
      {strategy.description !== null && (
        <section data-testid="public-description" className="flex flex-col gap-1.5">
          <h2 className="text-xs font-semibold text-ink-2">{t("strategies.description.publicHeading")}</h2>
          {/* Plain text only: React escapes it, and it is never parsed as HTML, Markdown or links. */}
          <p className="whitespace-pre-line break-words text-sm text-ink">{strategy.description}</p>
        </section>
      )}
      <section className="flex flex-col gap-3 rounded-md border border-rule bg-panel px-4 py-3">
        <PublicFigures
          strategy={strategy}
          returnInfo={<InfoButton disclosure={returnInfo} label={t("strategies.public.returnInfo")} />}
          capitalInfo={<InfoButton disclosure={capitalInfo} label={t("strategies.public.capitalInfo")} />}
        />
        <InfoText disclosure={returnInfo}>
          <p className="text-xs text-ink-3">{t("strategies.public.returnHint")}</p>
        </InfoText>
        <InfoText disclosure={capitalInfo}>
          <p className="text-xs text-ink-3">{t("strategies.public.capitalHint")}</p>
        </InfoText>
      </section>
      <SubscribePanel strategy={strategy} />
    </div>
  );
}

/**
 * One public strategy, for anyone signed in. A 404 is an ordinary answer here, not a fault: a strategy turned
 * private, archived or never public reads the same, so the page says only that it is not on the list.
 */
export function PublicStrategyPage() {
  const { t } = useTranslation();
  const { strategyId = "" } = useParams();
  const strategy = usePublicStrategy(strategyId);

  if (strategy.data !== undefined) return <PublicRecord strategy={strategy.data} />;

  const gone = strategy.error instanceof ApiError && strategy.error.status === 404;
  return (
    <div className="flex flex-col items-start gap-3">
      <BackToExplore />
      {strategy.status === "pending" && <p className="text-sm text-ink-2">{t("strategies.public.loading")}</p>}
      {gone && <p className="text-sm text-ink-2">{t("strategies.public.notFound")}</p>}
      {strategy.status === "error" && !gone && (
        <p role="alert" className="text-sm text-loss">
          {t("strategies.public.error")}
        </p>
      )}
    </div>
  );
}
