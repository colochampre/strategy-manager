import { useId, useState } from "react";
import { Save } from "lucide-react";
import { useTranslation } from "react-i18next";

import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";
import { StatusButton } from "@/shared/ui/StatusButton";
import { clockText } from "@/shared/lib/figure-text";
import { ShareAmount } from "@/features/strategies/ShareAmount";
import { ShareSlider } from "@/features/strategies/ShareSlider";
import { readStored } from "@/features/strategies/share-value";
import { DRAFT_REFUSAL_TEXT, useShareDraft } from "@/features/strategies/useShareDraft";
import { ApiError } from "@/shared/api/client";
import { useSetSubscriptionShare } from "@/shared/api/subscriptions";
import type { Strategy } from "@/shared/api/types";

interface PoolShareEditorProps {
  /** Only what it reads, so a subscriber's row, which holds no whole strategy, can use it. */
  strategy: Pick<Strategy, "id" | "subscription" | "archived_at">;
  /** The leverage being chosen beside this control, when one is: the amount line is read at it. Default: the saved one. */
  leverage?: number | undefined;
}

/** The text of a refused or failed save: the status (and the not-active code) decides, never the server's wording. */
function saveRefusal(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) return "strategies.detail.share.outOfRange";
    if (error.status === 409 && error.code === "SUBSCRIPTION_NOT_ACTIVE") return "strategies.detail.share.notActive";
    if (error.status === 404) return "strategies.detail.share.gone";
  }
  return "strategies.detail.share.saveFailed";
}

/**
 * The share of the signed-in user's pool a strategy asks for per trade (design § C). It is the user's own
 * subscription's share, saved on that subscription, never on the strategy (multi-user tasks C.12). The value
 * is one decimal string: the field keeps the text as typed, the handle follows it, and nothing is sent until
 * Save. Moving the handle or activating a stop is the one moment a decimal is rounded, to a whole number.
 */
export function PoolShareEditor({ strategy, leverage }: PoolShareEditorProps) {
  const { t } = useTranslation();
  const ids = { field: useId(), label: useId(), problem: useId() };
  const [saved, setSaved] = useState(false);
  const held = strategy.subscription;
  const save = useSetSubscriptionShare(strategy.id, held?.id ?? "");

  const stored = held === null ? null : readStored(held.allocation_percent);
  // Any movement of this control ends "Saved": a handle moved, a stop activated, a key typed. No timer.
  // The leverage the amount is read at: the one being chosen beside this control, else the seat's saved one.
  const { text, reading, handle, amount, readAt, changeText, changeStep } = useShareDraft(
    strategy.id,
    stored,
    () => setSaved(false),
    leverage ?? held?.leverage ?? 1,
  );
  // Each explanation owns its state: closed on every visit, kept through a save and a change of language.
  const shareInfo = useInfoDisclosure();
  const amountInfo = useInfoDisclosure();
  const refusal = save.status === "error" && (
    <p role="alert" className="text-sm text-loss">
      {t(saveRefusal(save.error))}
    </p>
  );
  if (held === null) {
    // No subscription, so no share of this user's pool to edit. A refused save that found it gone keeps its line.
    return (
      <section className="flex flex-col gap-3">
        <p className="text-sm text-ink-2">{t("strategies.detail.share.label")}</p>
        <p className="text-sm text-ink-2">{t("strategies.detail.share.none")}</p>
        {refusal}
      </section>
    );
  }
  if (stored === null) {
    // Never a guess: a stored value that is not a plain decimal gets no track, no field and no Save.
    return (
      <section className="flex flex-col gap-3">
        <p className="text-sm text-ink-2">{t("strategies.detail.share.label")}</p>
        <p className="text-sm text-ink-2">{t("strategies.detail.share.unreadable")}</p>
      </section>
    );
  }

  // A LEAVING subscription takes no share change (the API answers 409), so it reads as it stands.
  const leaving = held.status !== "ACTIVE";
  const readOnly = strategy.archived_at !== null || leaving;
  const changed = reading.valid && reading.canonical !== stored;
  const busy = save.isPending;

  // A button that reads "Saved" is disabled, so a save never starts while "Saved" stands: a refusal and
  // "Saved" are never on screen together. Set on success only, never on settle.
  const handleSave = () => {
    if (!reading.valid || !changed || readOnly || busy) return;
    save.mutate(reading.canonical, { onSuccess: () => setSaved(true) });
  };
  const saveText = t("strategies.detail.share.save");
  const savingText = t("strategies.detail.share.saving");
  const savedText = t("strategies.detail.saved");

  return (
    // Named by its label: several editors on one page each have a Save that says only "Save".
    <section aria-labelledby={ids.label} className="flex flex-col gap-3">
      <div className="flex items-start">
        <label id={ids.label} htmlFor={ids.field} className="text-sm leading-5 text-ink-2">
          {t("strategies.detail.share.label")}
        </label>
        <InfoButton disclosure={shareInfo} label={t("strategies.detail.share.info")} />
      </div>
      <InfoText disclosure={shareInfo}>
        <p className="text-xs text-ink-3">{t("strategies.detail.share.hint")}</p>
      </InfoText>
      <ShareSlider
        fieldId={ids.field}
        labelId={ids.label}
        text={text}
        handle={handle}
        value={reading.valid ? reading.canonical : null}
        disabled={readOnly || busy}
        invalid={!reading.valid}
        describedBy={reading.valid ? undefined : ids.problem}
        onText={changeText}
        onHandle={changeStep}
        onStop={changeStep}
        // Save is on the field's row, as wide as its own text needs; the field takes the width that is left.
        // Both start at the top, so Save does not move when anything opens or appears under the row.
        action={
          <div className="flex shrink-0 items-start gap-x-3">
            <StatusButton
              texts={[saveText, savingText, savedText]}
              shown={busy ? savingText : saved ? savedText : saveText}
              message={saved ? savedText : null}
              onClick={handleSave}
              disabled={readOnly || busy || !changed || saved}
              icon={Save}
              iconOnly
              busy={busy}
              look="primary"
            />
          </div>
        }
      />
      <ShareAmount
        view={amount}
        trailing={<InfoButton disclosure={amountInfo} label={t("strategies.detail.share.amountInfo")} />}
        explanation={
          <InfoText disclosure={amountInfo}>
            {readAt !== null && (
              <p className="text-xs text-ink-3">{t("strategies.detail.share.amountHint", { time: clockText(readAt) ?? readAt })}</p>
            )}
            <p className="text-xs text-ink-3">{t("strategies.detail.share.pairMinimumNote")}</p>
          </InfoText>
        }
      />
      {!reading.valid && (
        <p id={ids.problem} className="text-xs text-loss">
          {t(DRAFT_REFUSAL_TEXT[reading.refusal])}
        </p>
      )}
      {leaving && <p className="text-sm text-ink-2">{t("strategies.detail.share.leaving")}</p>}
      {refusal}
    </section>
  );
}
