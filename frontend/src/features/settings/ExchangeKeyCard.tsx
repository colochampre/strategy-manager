import type { TFunction } from "i18next";
import { useId } from "react";
import { useTranslation } from "react-i18next";

import type { CredentialEntry, StoredCredential } from "@/shared/api/credentials";
import { KeyMark } from "@/shared/credentials/KeyMark";
import { keyMark, keyState } from "@/shared/credentials/key-state";
import { cn } from "@/shared/lib/cn";
import { dayText } from "@/shared/lib/day-text";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";

export interface ExchangeKeyCardProps {
  /** The exchange's id as the API spells it. */
  exchange: string;
  /** Its row of `GET /credentials`, or `undefined` when it is not listed. */
  entry: CredentialEntry | undefined;
  /** Whether a pool of this exchange is enabled: `null` while that is not known. */
  poolOn: boolean | null;
  /** Whether the panel manages a key for this exchange (it is in `served-exchanges.json`). */
  served: boolean;
}

/** The four dots that stand for the part of the key the panel never has. */
const DOTS = "••••";

const SENTENCE = "max-w-[70ch] text-[13px]";

/**
 * A tag cannot break inside (`whitespace-nowrap`) and the list wraps, so when the
 * width runs out a WHOLE tag moves to the next line. There is no separator
 * character anywhere on the card, so no line can begin with one.
 */
const TAG = "whitespace-nowrap rounded border px-2 py-0.5 font-mono text-xs";

/**
 * What a tag says about its fact. They differ in more than colour:
 * - `checked`: the exchange itself showed it to the application (filled);
 * - `confirmed`: the owner's word, with the day he gave it (hollow, dashed);
 * - `unrecorded`: nothing is on record about this fact (hollow, dashed, dimmer).
 */
type TagLook = "checked" | "confirmed" | "unrecorded";

const LOOK: Record<TagLook, string> = {
  checked: "border-rule bg-panel-2 text-ink-2",
  confirmed: "border-dashed border-rule-strong text-ink-2",
  unrecorded: "border-dashed border-rule-strong text-ink-3",
};

/** The source a fact has when the exchange itself showed it to the application. */
const VERIFIED = "VERIFIED";
/** The source of a fact the owner stated, with the day he did. */
const OWNER_CONFIRMED = "OWNER_CONFIRMED";
/** What migration 0027 wrote for every key that existed before the system recorded how it was checked. */
const UNRECORDED = "UNRECORDED";

interface Tag {
  id: string;
  text: string;
  look: TagLook;
}

/**
 * The facts of a stored key as tags, in the order of design § D. One phrase per
 * fact: trade is said by exactly one of `trades`, the `read-only` mark, `trade
 * confirmed` and `trade not verified`, and withdrawal by exactly one of `no
 * withdrawal`, `withdraw confirmed` and `withdraw not verified`. A source value
 * the panel does not know is drawn as not verified, never as checked, and a
 * confirmation with no day is not verified either: "confirmed" cannot be said
 * without the day.
 */
function tagsOf(key: StoredCredential, language: string, t: TFunction): Tag[] {
  const tags: Tag[] = [];
  const tradeChecked = key.trade_capability_source === VERIFIED;
  const withdrawChecked = key.withdraw_check === VERIFIED;

  if (tradeChecked) {
    if (key.trade_capable) tags.push({ id: "trades", text: t("settings.card.tag.trades"), look: "checked" });
  } else if (key.validated_at !== null) {
    tags.push({ id: "reads", text: t("settings.card.tag.reads"), look: "checked" });
  }
  if (withdrawChecked) tags.push({ id: "noWithdrawal", text: t("settings.card.tag.noWithdrawal"), look: "checked" });
  if (key.internal_transfer === true) tags.push({ id: "transfers", text: t("settings.card.tag.transfers"), look: "checked" });
  if (key.internal_transfer === false) {
    tags.push({ id: "noTransfers", text: t("settings.card.tag.noTransfers"), look: "checked" });
  }

  if (!tradeChecked) {
    const day = key.trade_capability_source === OWNER_CONFIRMED ? key.trade_confirmed_at : null;
    tags.push(
      day === null
        ? { id: "tradeNotVerified", text: t("settings.card.tag.tradeNotVerified"), look: "unrecorded" }
        : {
            id: "tradeConfirmed",
            text: t("settings.card.tag.tradeConfirmed", { date: dayText(day, language) }),
            look: "confirmed",
          },
    );
  }
  if (!withdrawChecked) {
    const day = key.withdraw_check === OWNER_CONFIRMED ? key.withdraw_confirmed_at : null;
    tags.push(
      day === null
        ? { id: "withdrawNotVerified", text: t("settings.card.tag.withdrawNotVerified"), look: "unrecorded" }
        : {
            id: "withdrawConfirmed",
            text: t("settings.card.tag.withdrawConfirmed", { date: dayText(day, language) }),
            look: "confirmed",
          },
    );
  }
  return tags;
}

function storedOf(entry: CredentialEntry | undefined): StoredCredential | null {
  return entry?.status === "STORED" ? entry : null;
}

/**
 * The key hint: the label, four dots and the last four characters the API sent,
 * and nothing more of the key. The drawn pieces are hidden from assistive
 * technology and a hidden text says it in words ("key ending in 7Q2d"). It is a
 * paragraph and not a heading: it is a value, nothing is filed under it, so the
 * card stays named by its one `h3`.
 */
function KeyHint({ last4 }: { last4: string }) {
  const { t } = useTranslation();
  return (
    <p className="font-mono text-xl font-semibold whitespace-nowrap">
      <span aria-hidden="true">
        <span className="text-[13px] font-normal text-ink-3">{t("settings.card.keyLabel")}</span>{" "}
        <span className="font-normal text-ink-3">{DOTS}</span>
        <span className="tracking-wider text-ink">{last4}</span>
      </span>
      <span className="sr-only">{t("settings.card.keyEnding", { last4 })}</span>
    </p>
  );
}

/**
 * One exchange's key, in exactly one state (design § D): a key that trades, a
 * key that cannot trade, a keyless exchange with a pool on (degraded), or a
 * keyless exchange with none. Amber appears only where the owner has something
 * to do: the `read-only` and degraded `no key` marks, the border and the
 * sentence with them. An exchange the panel does not manage has no control.
 *
 * It decides nothing: the state and the mark come from the same function the
 * exchange tabs call.
 */
export function ExchangeKeyCard({ exchange, entry, poolOn, served }: ExchangeKeyCardProps) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const state = keyState(entry, poolOn);
  const mark = keyMark(state);
  const amber = mark?.tone === "amber";
  const key = storedOf(entry);
  const nameKey = `exchanges.${exchange}`;
  const name = i18n.exists(nameKey) ? t(nameKey) : exchange;
  const disclosure = useInfoDisclosure();
  const tags = key === null ? [] : tagsOf(key, i18n.language, t);
  const confirmedDay = tags.some((tag) => tag.look === "confirmed");
  const unrecordedKey =
    key !== null && key.trade_capability_source === UNRECORDED && key.withdraw_check === UNRECORDED;

  /** The sentence of the state; a keyless exchange the panel does not manage gets the short one. */
  const sentence = (() => {
    switch (state) {
      case "readOnly":
        return { text: t("settings.card.readOnly", { exchange: name }), tone: "text-decision" };
      case "degraded":
        return {
          text: served ? t("settings.card.degraded", { exchange: name }) : t("settings.card.emptyNotServed"),
          tone: "text-decision",
        };
      case "empty":
        return {
          text: served ? t("settings.card.empty", { exchange: name }) : t("settings.card.emptyNotServed"),
          tone: "text-ink-2",
        };
      case "key":
        return null;
    }
  })();

  return (
    <article
      aria-labelledby={headingId}
      className={cn(
        "grid grid-cols-1 items-start gap-x-6 gap-y-3 rounded-lg border bg-panel p-5 sm:grid-cols-[minmax(0,1fr)_auto]",
        amber ? "border-decision" : "border-rule",
      )}
    >
      <div className="flex min-w-0 flex-col gap-1">
        <h3 id={headingId} className="font-display text-[17px] font-semibold text-ink">
          {name}
        </h3>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
          {key !== null ? (
            <>
              <KeyHint last4={key.last4} />
              <p className="font-mono text-xs text-ink-3 whitespace-nowrap">
                {key.validated_at === null
                  ? t("settings.card.notValidated")
                  : t("settings.card.checkedOn", { date: dayText(key.validated_at, i18n.language) })}
              </p>
            </>
          ) : (
            mark !== null && <KeyMark mark={mark} variant="tag" as="p" />
          )}
        </div>
      </div>

      <div className="flex min-w-0 flex-col gap-2.5 sm:col-span-2">
        {key !== null && (
          <ul aria-label={t("settings.card.facts")} className="flex flex-wrap items-center gap-1.5">
            {state === "readOnly" && mark !== null && <KeyMark mark={mark} variant="tag" as="li" />}
            {tags.map((tag) => (
              <li key={tag.id} className={cn(TAG, LOOK[tag.look])}>
                {tag.text}
              </li>
            ))}
            {confirmedDay && (
              <li className="flex">
                <InfoButton disclosure={disclosure} label={t("settings.card.confirmedInfo")} />
              </li>
            )}
          </ul>
        )}
        {confirmedDay && (
          <InfoText disclosure={disclosure}>
            <p className={cn(SENTENCE, "text-ink-2")}>{t("settings.card.confirmedHint", { exchange: name })}</p>
          </InfoText>
        )}
        {unrecordedKey && served && <p className={cn(SENTENCE, "text-ink-3")}>{t("settings.card.unrecordedHint")}</p>}
        {sentence !== null &&<p className={cn(SENTENCE, sentence.tone)}>{sentence.text}</p>}
        {!served && <p className={cn(SENTENCE, "text-ink-3")}>{t("settings.card.notServed", { exchange: name })}</p>}
      </div>

      <div className="flex flex-wrap items-start gap-2 empty:hidden sm:col-start-2 sm:row-start-1" />
    </article>
  );
}
