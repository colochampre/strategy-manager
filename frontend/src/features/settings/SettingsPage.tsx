import { useId } from "react";
import { useTranslation } from "react-i18next";

import { ExchangeKeyCard } from "@/features/settings/ExchangeKeyCard";
import { useCredentials } from "@/shared/api/credentials";
import { usePools } from "@/shared/api/pools";
import { exchangeList, knownPools, poolOn } from "@/shared/credentials/key-state";
import served from "@/shared/credentials/served-exchanges.json";

/** The ids of the exchanges the panel manages a key for, in the file's display order. */
const SERVED = Object.keys(served);

const RETRY_BUTTON = "min-h-11 rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2";

/**
 * Settings: one card per exchange, drawn from `GET /api/credentials` and
 * `GET /api/pools` (design § B). The page reads, and in this unit it changes
 * nothing.
 *
 * Every failure to read is a line on the page. A card says "No key stored" or
 * "the key is fine" only about what was read: while the credentials are not
 * known, or when the first read failed, there is no card at all, because a card
 * drawn from the file alone would claim a key does not exist that the panel could
 * not look for. When a later read fails the cards stay, under a line that says
 * they may be out of date. When the pools could not be read no exchange is
 * called degraded on a guess, and one line says so.
 *
 * The page has no width cap of its own: like Strategies it fills the shell's
 * column, so a card ends at the same place on both (decision 60). What is capped
 * is each sentence, inside its card.
 */
export function SettingsPage() {
  const { t } = useTranslation();
  const titleId = useId();
  const credentials = useCredentials();
  const pools = usePools();
  const poolList = knownPools(pools);

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-2xl font-bold text-ink">{t("settings.title")}</h1>
      <section aria-labelledby={titleId} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <h2 id={titleId} className="font-display text-base font-semibold text-ink">
            {t("settings.keys.title")}
          </h2>
          <p className="text-sm text-ink-2">{t("settings.keys.intro")}</p>
        </div>

        {credentials.status === "pending" && (
          <p role="status" className="text-[13px] text-ink-2">
            {t("settings.keys.loading")}
          </p>
        )}

        {credentials.status === "error" && credentials.data === undefined && (
          <div className="flex flex-wrap items-center gap-3">
            <p role="alert" className="text-[13px] text-loss">
              {t("settings.keys.error")}
            </p>
            <button type="button" className={RETRY_BUTTON} onClick={() => void credentials.refetch()}>
              {t("settings.keys.retry")}
            </button>
          </div>
        )}

        {credentials.data !== undefined && (
          <>
            {credentials.isError && (
              <div className="flex flex-wrap items-center gap-3">
                <p role="alert" className="text-[13px] text-loss">
                  {t("settings.keys.stale")}
                </p>
                <button type="button" className={RETRY_BUTTON} onClick={() => void credentials.refetch()}>
                  {t("settings.keys.retry")}
                </button>
              </div>
            )}
            {pools.isError && <p className="text-[13px] text-ink-2">{t("settings.keys.poolsUnknown")}</p>}
            <ul aria-labelledby={titleId} className="flex flex-col gap-4">
              {exchangeList(SERVED, credentials.data, poolList ?? []).map((exchange) => (
                <li key={exchange}>
                  <ExchangeKeyCard
                    exchange={exchange}
                    entry={credentials.data.find((row) => row.exchange === exchange)}
                    poolOn={poolOn(exchange, poolList)}
                    served={SERVED.includes(exchange)}
                  />
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}
