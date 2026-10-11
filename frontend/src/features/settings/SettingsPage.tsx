import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ExchangeKeyCard } from "@/features/settings/ExchangeKeyCard";
import { exchangeName } from "@/features/settings/exchange-name";
import { KeyEntryForm, type SavedKey } from "@/features/settings/KeyEntryForm";
import { useCredentials } from "@/shared/api/credentials";
import { usePools } from "@/shared/api/pools";
import { exchangeList, knownPools, poolOn } from "@/shared/credentials/key-state";
import served from "@/shared/credentials/served-exchanges.json";

/** The ids of the exchanges the panel manages a key for, in the file's display order. */
const SERVED = Object.keys(served);

/** The confirmations each served exchange asks for, by name (an exchange the file lists with none asks for none). */
const CONFIRMATIONS: Readonly<Record<string, readonly string[]>> = Object.fromEntries(
  Object.entries(served).map(([id, entry]) => [id, entry.confirmations]),
);

const RETRY_BUTTON = "min-h-11 rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2";

/**
 * Settings: one card per exchange, drawn from `GET /api/credentials` and
 * `GET /api/pools` (design § B). It holds the one open key form, and the end of
 * a save that worked: the form closes on the answer, the card says so, the focus
 * returns to the toggle and one hidden status region tells a screen reader.
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
  const { t, i18n } = useTranslation();
  const titleId = useId();
  const credentials = useCredentials();
  const pools = usePools();
  const poolList = knownPools(pools);
  /** The exchange whose form is open, or none: the page holds at most one, so opening another empties this one. */
  const [openForm, setOpenForm] = useState<string | null>(null);
  /** A save is in flight: every button of every card is disabled meanwhile. */
  const [saving, setSaving] = useState(false);
  /** Which toggle should have the focus once the form has left the document; a new object each time asks again. */
  const [focusRequest, setFocusRequest] = useState<{ exchange: string } | null>(null);
  const toggles = useRef(new Map<string, HTMLButtonElement>());
  const queryClient = useQueryClient();
  /**
   * The last save that worked, kept until the owner does the next thing on the page. `last4` is the answer's, only
   * when it was exactly four characters; `listStamp` is when `['credentials']` was last read, so that the card
   * knows whether the list has been read again since.
   */
  const [lastSave, setLastSave] = useState<{
    exchange: string;
    last4: string | null;
    readOnly: boolean;
    listStamp: number;
    /** Ends at the next thing the owner does; the pending view of a list not read again does not end with it. */
    noticeOn: boolean;
  } | null>(null);
  /** What the always-present status region says; it is the only live region the save uses. */
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    if (focusRequest !== null) toggles.current.get(focusRequest.exchange)?.focus();
  }, [focusRequest]);

  /** The next thing the owner does ends the notice of a save: no timer (design § F). */
  function openFormOf(exchange: string) {
    setLastSave((current) => (current === null ? null : { ...current, noticeOn: false }));
    setAnnouncement("");
    setOpenForm(exchange);
  }

  /**
   * A save worked: the form closes on the answer, without waiting for the lists, and the page remembers only what
   * the ANSWER said. The focus goes to the toggle once the form has left the document, and the status region
   * tells a screen reader, with the card's read-only sentence after it when the key cannot trade.
   */
  function saved(exchange: string, answer: SavedKey) {
    const stamp = queryClient.getQueryState(["credentials"])?.dataUpdatedAt ?? 0;
    setLastSave({ exchange, last4: answer.last4, readOnly: answer.readOnly, listStamp: stamp, noticeOn: true });
    setAnnouncement(
      [
        answer.last4 === null ? t("settings.card.savedNoHint") : t("settings.card.saved", { last4: answer.last4 }),
        answer.readOnly ? t("settings.card.readOnly", { exchange: exchangeName(t, i18n, exchange) }) : null,
      ]
        .filter((part) => part !== null)
        .join(" "),
    );
    setOpenForm(null);
    setFocusRequest({ exchange });
  }

  /** Closes the form of `exchange` (unmounting and so emptying it) and returns the focus to the toggle that opened it. */
  function closeForm(exchange: string) {
    setOpenForm(null);
    setFocusRequest({ exchange });
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-2xl font-bold text-ink">{t("settings.title")}</h1>
      {/* The one status region: always in the document, hidden from sight, said once at a save. */}
      <p role="status" className="sr-only">
        {announcement}
      </p>
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
                    open={openForm === exchange}
                    busy={saving}
                    saved={
                      lastSave?.exchange === exchange
                        ? {
                            last4: lastSave.last4,
                            readOnly: lastSave.readOnly,
                            // Read again since the save only when `dataUpdatedAt` moved past the stamp; a failed
                            // read does not move it, so the card stays drawn from the answer.
                            pending: credentials.dataUpdatedAt <= lastSave.listStamp,
                            showNotice: lastSave.noticeOn,
                          }
                        : null
                    }
                    onToggle={() => (openForm === exchange ? closeForm(exchange) : openFormOf(exchange))}
                    toggleRef={(element) => {
                      if (element === null) toggles.current.delete(exchange);
                      else toggles.current.set(exchange, element);
                    }}
                  >
                    <KeyEntryForm
                      id={`key-form-${exchange}`}
                      exchange={exchange}
                      name={exchangeName(t, i18n, exchange)}
                      hasKey={
                        credentials.data.some((row) => row.exchange === exchange && row.status === "STORED") ||
                        // A key saved a moment ago is stored even if the list has not been read again.
                        (lastSave?.exchange === exchange && credentials.dataUpdatedAt <= lastSave.listStamp)
                      }
                      confirmations={CONFIRMATIONS[exchange] ?? []}
                      onClose={() => closeForm(exchange)}
                      onSaved={(answer) => saved(exchange, answer)}
                      onBusyChange={setSaving}
                    />
                  </ExchangeKeyCard>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}
