import type { TFunction } from "i18next";
import { type ReactNode, type Ref, useId } from "react";
import { KeyRound } from "lucide-react";
import { useTranslation } from "react-i18next";

import { exchangeName } from "@/shared/exchanges/exchange-name";
import { ExchangeWordmark } from "@/shared/exchanges/ExchangeWordmark";
import type { CredentialEntry, StoredCredential } from "@/shared/api/credentials";
import { KeyMark } from "@/shared/credentials/KeyMark";
import { type KeyState, keyMark, keyState } from "@/shared/credentials/key-state";
import { cn } from "@/shared/lib/cn";
import { dayText } from "@/shared/lib/day-text";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";
import { Pill } from "@/shared/ui/Pill";

/** A save that worked, as the row draws it. */
export interface SavedView {
  /** The answer's four characters, or none when it did not send exactly four. */
  last4: string | null;
  /** Whether the answer said the key cannot trade. */
  readOnly: boolean;
  /** The list has not been read again since the save (or its read failed): draw the row from the answer. */
  pending: boolean;
  /**
   * Whether the notice is still shown once the list is read: it ends at the next thing the owner does. While
   * `pending` the notice stays, because the row still needs the sentence that says the rest is not read yet.
   */
  showNotice: boolean;
}

export interface ExchangeKeyRowProps {
  /** The exchange's id as the API spells it. */
  exchange: string;
  /** Its row of `GET /credentials`, or `undefined` when it is not listed. */
  entry: CredentialEntry | undefined;
  /** Whether a pool of this exchange is enabled: `null` while that is not known. */
  poolOn: boolean | null;
  /** Whether the panel manages a key for this exchange (it is in `served-exchanges.json`). */
  served: boolean;
  /** Whether this row's key form is open. */
  open: boolean;
  /** The toggle was pressed: it opens the form, or closes it when it is open. */
  onToggle: () => void;
  /** A save is in flight somewhere on the page: every button of the row is disabled. */
  busy?: boolean;
  /** Receives the toggle, so the page can put the focus back on it after the form has left the document. */
  toggleRef?: Ref<HTMLButtonElement>;
  /** What the last save on this row said, until the owner does something else on the page. */
  saved?: SavedView | null;
  /** The key form, drawn in a row of its own under the key's row when `open`. */
  children?: ReactNode;
  /**
   * The page's `Delete key` control, drawn after the toggle of a served row and never on one the panel does not
   * manage. The page gives it, so this row needs no query client; the control draws nothing when no key is stored.
   */
  deleteSlot?: ReactNode;
  /** The filter hides the row; it stays mounted, with its form and what was typed in it. */
  hidden?: boolean;
}

/** The number of columns of the keys' grid: the detail and the form rows span them all. */
export const KEY_COLUMNS = 6;

/** The four dots that stand for the part of the key the panel never has. */
const DOTS = "••••";

const SENTENCE = "max-w-[70ch] text-[13px]";

/** A cell of the grid (ex6 `td`): 12 px across, 11 px down, 13 px, never wrapping. */
const CELL = "px-3 py-[11px] text-[13px] whitespace-nowrap";

/**
 * A tag cannot break inside (`whitespace-nowrap`) and the list wraps, so when the
 * width runs out a WHOLE tag moves to the next line. There is no separator
 * character anywhere on the row, so no line can begin with one.
 */
const TAG = "whitespace-nowrap rounded border px-2 py-0.5 font-mono text-xs";

/**
 * What a tag says about its fact. They differ in more than colour:
 * - `checked`: the exchange itself showed it to the application (filled);
 * - `confirmed`: the owner's word, with the day it was given (hollow, dashed);
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
/** The source of a fact the owner stated, with the day it was stated. */
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

/** The day a key was stored as `dd/mm/yyyy` (ex6), in UTC like the other days of the panel; none for a day it cannot read. */
export function linkedOn(iso: string | null): string | null {
  if (iso === null) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const two = (value: number) => String(value).padStart(2, "0");
  return `${two(date.getUTCDate())}/${two(date.getUTCMonth() + 1)}/${date.getUTCFullYear()}`;
}

/**
 * The key's hint, the four dots and the last four characters the API sent, in mono, and nothing more of the key.
 * The drawn pieces are hidden from assistive technology and a hidden text says it in words ("key ending in 7Q2d").
 */
function KeyHint({ last4 }: { last4: string }) {
  const { t } = useTranslation();
  return (
    <span className="font-mono tabular-nums">
      <span aria-hidden="true">
        <span className="text-ink-3">{DOTS}</span>
        <span className="text-ink">{last4}</span>
      </span>
      <span className="sr-only">{t("settings.card.keyEnding", { last4 })}</span>
    </span>
  );
}

/** A cell with nothing to say: a dash, read as "no data". */
function Dash() {
  const { t } = useTranslation();
  return (
    <>
      <span aria-hidden="true" className="text-ink-3">
        —
      </span>
      <span className="sr-only">{t("exchangesPage.none")}</span>
    </>
  );
}

/**
 * One exchange's key as a row of the grid of Vincular exchange (ex6), in exactly one state (design § D): a key
 * that trades, a key that cannot trade, a keyless exchange with a pool on (degraded), or a keyless exchange with
 * none. The row says the exchange, the key's hint, what it may do, its state, the day it was linked and the
 * actions; whatever needs a sentence (the facts checked, a save's notice, the warning of a state that asks the
 * owner to act) sits in a row under it that spans every column, and the key form in another. Amber appears only
 * where the owner has something to do: the `read-only` and degraded `no key` marks and the sentences with them.
 * An exchange the panel does not manage has no control.
 *
 * It decides nothing: the state and the mark come from the same function the exchange tabs call.
 */
export function ExchangeKeyRow({
  exchange,
  entry,
  poolOn,
  served,
  open,
  onToggle,
  busy = false,
  toggleRef,
  saved,
  children,
  deleteSlot,
  hidden = false,
}: ExchangeKeyRowProps) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  /**
   * Until the list has been read again after a save, the row is drawn from the
   * save's own answer and never from the list's old entry, so it can never show the
   * key stored before as if nothing had happened (design § F, decision 57).
   */
  const fromAnswer = saved != null && saved.pending;
  const state: KeyState = fromAnswer ? (saved.readOnly ? "readOnly" : "key") : keyState(entry, poolOn);
  const mark = keyMark(state);
  const key = fromAnswer ? null : storedOf(entry);
  const toggleId = useId();
  /** "Replace key" when a key is stored or was just saved on this row, "Add key" otherwise. */
  const holdsKey = key !== null || fromAnswer;
  const notice =
    saved == null || !(saved.pending || saved.showNotice)
      ? null
      : [
          saved.last4 === null ? t("settings.card.savedNoHint") : t("settings.card.saved", { last4: saved.last4 }),
          saved.pending ? t("settings.card.savedPending") : null,
        ]
          .filter((part) => part !== null)
          .join(" ");
  const name = exchangeName(t, i18n, exchange);
  const disclosure = useInfoDisclosure();
  const tags = key === null ? [] : tagsOf(key, i18n.language, t);
  const confirmedDay = tags.some((tag) => tag.look === "confirmed");
  const unrecordedKey =
    key !== null && key.trade_capability_source === UNRECORDED && key.withdraw_check === UNRECORDED;
  const canTrade = fromAnswer ? !saved.readOnly : key?.trade_capable === true;
  const toggleLabel = `${holdsKey ? t("settings.card.replace") : t("settings.card.add")} ${name}`;

  /** The sentence of the state; a keyless exchange the panel does not manage gets the short one. */
  const sentence = (() => {
    switch (state) {
      case "readOnly":
        // The amber mark says it (L13).
        return null;
      case "degraded":
        // The amber `no key` pill says it (L13); a keyless exchange the panel does not manage keeps the short line.
        return served ? null : { text: t("settings.card.emptyNotServed"), tone: "text-decision" };
      case "empty":
        return {
          text: served ? t("settings.card.empty", { exchange: name }) : t("settings.card.emptyNotServed"),
          tone: "text-ink-2",
        };
      case "key":
        return null;
    }
  })();

  const checkedLine =
    key === null
      ? null
      : key.validated_at === null
        ? t("settings.card.notValidated")
        : t("settings.card.checkedOn", { date: dayText(key.validated_at, i18n.language) });
  const facts = key !== null || (fromAnswer && state === "readOnly");
  const hasDetail =
    notice !== null ||
    checkedLine !== null ||
    facts ||
    (unrecordedKey && served) ||
    sentence !== null ||
    !served;

  return (
    <tbody aria-labelledby={headingId} hidden={hidden} className="border-b border-rule-soft last:border-b-0">
      <tr>
        <td className={CELL}>
          {/* The exchange's own logotype, named by its display name; its capitalised name where it has none (decision 77). */}
          <h3 id={headingId} className="flex h-6 items-center font-display text-[15px] font-semibold text-ink">
            <ExchangeWordmark exchange={exchange} className="h-3" />
          </h3>
        </td>
        <td className={CELL}>
          {fromAnswer ? (
            // The saved key's hint, with no date: the list that would hold its date has not been read.
            saved.last4 !== null ? <KeyHint last4={saved.last4} /> : <Dash />
          ) : key !== null ? (
            <KeyHint last4={key.last4} />
          ) : (
            <Dash />
          )}
        </td>
        <td className={CELL}>
          {holdsKey ? (
            canTrade ? (
              <Pill tone="gain">{t("exchangesPage.permission.trading")}</Pill>
            ) : (
              <Pill tone="neutral">{t("exchangesPage.permission.readOnly")}</Pill>
            )
          ) : (
            <Dash />
          )}
        </td>
        <td className={CELL}>
          {holdsKey ? (
            <Pill tone="gain" dot>
              {t("exchangesPage.state.active")}
            </Pill>
          ) : mark !== null ? (
            <KeyMark mark={mark} variant="pill" />
          ) : (
            <Dash />
          )}
        </td>
        <td className={cn(CELL, "font-mono tabular-nums")}>
          {key !== null && linkedOn(key.stored_at) !== null ? linkedOn(key.stored_at) : <Dash />}
        </td>
        <td className={cn(CELL, "text-right")}>
          <div className="flex justify-end gap-1.5">
            {served && (
              <button
                ref={toggleRef}
                id={toggleId}
                type="button"
                aria-label={toggleLabel}
                title={holdsKey ? t("settings.card.replace") : t("settings.card.add")}
                aria-expanded={open}
                aria-controls={`key-form-${exchange}`}
                disabled={busy}
                onClick={onToggle}
                className={cn(
                  "inline-flex size-8 shrink-0 items-center justify-center rounded-lg border bg-panel transition-colors hover:bg-panel-2 motion-reduce:transition-none disabled:opacity-50 aria-expanded:bg-panel-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain",
                  holdsKey ? "border-rule text-ink-2" : "border-gain text-gain",
                )}
              >
                <KeyRound aria-hidden="true" className="size-4 shrink-0" />
              </button>
            )}
            {served && deleteSlot}
          </div>
        </td>
      </tr>
      {hasDetail && (
        <tr>
          <td colSpan={KEY_COLUMNS} className="px-3 pt-0 pb-3">
            <div className="flex min-w-0 flex-col gap-2.5">
              {notice !== null && <p className={cn(SENTENCE, "text-ink-2")}>{notice}</p>}
              {checkedLine !== null && <p className="font-mono text-xs whitespace-nowrap text-ink-3">{checkedLine}</p>}
              {facts && (
                <ul aria-label={t("settings.card.facts")} className="flex flex-wrap items-center gap-1.5">
                  {state === "readOnly" && mark !== null && <KeyMark mark={mark} as="li" />}
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
              {unrecordedKey && served && (
                <p className={cn(SENTENCE, "text-ink-3")}>{t("settings.card.unrecordedHint")}</p>
              )}
              {sentence !== null && <p className={cn(SENTENCE, sentence.tone)}>{sentence.text}</p>}
              {!served && <p className={cn(SENTENCE, "text-ink-3")}>{t("settings.card.notServed", { exchange: name })}</p>}
            </div>
          </td>
        </tr>
      )}
      {open && children !== undefined && (
        <tr>
          <td colSpan={KEY_COLUMNS} className="px-3 pt-0 pb-4">
            <div className="min-w-0">{children}</div>
          </td>
        </tr>
      )}
    </tbody>
  );
}
