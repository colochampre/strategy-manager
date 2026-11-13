import { useId, useState } from "react";
import { Save } from "lucide-react";
import { useTranslation } from "react-i18next";

import { LeverageSlider } from "@/features/strategies/LeverageSlider";
import { leverageProblem, useLeverageDraft, type LeverageDraft } from "@/features/strategies/useLeverageDraft";
import { maxLeverage } from "@/features/strategies/stop-level";
import { ApiError } from "@/shared/api/client";
import { useSetSubscriptionLeverage } from "@/shared/api/subscriptions";
import type { Strategy } from "@/shared/api/types";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";
import { StatusButton } from "@/shared/ui/StatusButton";

interface SubscriptionLeverageEditorProps {
  /** Only what it reads, so a subscriber's row, which holds no whole strategy, can use it. */
  strategy: Pick<Strategy, "id" | "subscription" | "archived_at" | "stop_loss_pct">;
  /** The draft, when a parent shares it with the share line; the editor keeps its own otherwise. */
  draft?: LeverageDraft | undefined;
}

/** The text of a refused or failed save: the status (and the not-active code) decides, never the server's wording. */
function saveRefusal(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) return "strategies.leverage.outOfRange";
    if (error.status === 409 && error.code === "SUBSCRIPTION_NOT_ACTIVE") return "strategies.leverage.notActive";
    if (error.status === 409 && error.code === "LEVERAGE_ABOVE_STOP_CAP") return "strategies.leverage.aboveCapRefused";
    if (error.status === 404) return "strategies.leverage.gone";
  }
  return "strategies.leverage.saveFailed";
}

/**
 * The leverage the signed-in user's subscription opens with. It has its own Save, apart from the share's:
 * the two are separate fields of the subscription and one is never sent with the other. The field keeps the
 * text as typed, the handle follows it, and nothing is sent until Save. A change applies at the next
 * opening; the system sets it on the exchange before opening.
 */
export function SubscriptionLeverageEditor({ strategy, draft }: SubscriptionLeverageEditorProps) {
  const { t } = useTranslation();
  const ids = { field: useId(), label: useId(), problem: useId() };
  const [saved, setSaved] = useState(false);
  const held = strategy.subscription;
  const save = useSetSubscriptionLeverage(strategy.id, held?.id ?? "");
  const info = useInfoDisclosure();
  // Any movement of this control ends "Saved": a handle moved, a stop activated, a key typed. No timer.
  const max = maxLeverage(strategy.stop_loss_pct);
  const own = useLeverageDraft(held?.leverage ?? 1, undefined, max);
  const shared = draft ?? own;
  const { text, reading, handle } = shared;
  const changeText = (next: string) => {
    shared.changeText(next);
    setSaved(false);
  };
  const changeStep = (step: number) => {
    shared.changeStep(step);
    setSaved(false);
  };

  if (held === null) return null;

  // A LEAVING subscription takes no change (the API answers 409), so it reads as it stands.
  const readOnly = strategy.archived_at !== null || held.status !== "ACTIVE";
  const changed = reading.valid && reading.value !== held.leverage;
  const busy = save.isPending;

  // A button that reads "Saved" is disabled, so a save never starts while "Saved" stands. Set on success only.
  const handleSave = () => {
    if (!reading.valid || !changed || readOnly || busy) return;
    save.mutate(reading.value, { onSuccess: () => setSaved(true) });
  };
  const saveText = t("strategies.leverage.save");
  const savingText = t("strategies.leverage.saving");
  const savedText = t("strategies.detail.saved");

  return (
    // Named by its label: several editors on one page each have a Save that says only "Save".
    <section aria-labelledby={ids.label} className="flex flex-col gap-3">
      <div className="flex items-start">
        <label id={ids.label} htmlFor={ids.field} className="text-sm leading-5 text-ink-2">
          {t("strategies.leverage.label")}
        </label>
        <InfoButton disclosure={info} label={t("strategies.leverage.info")} />
      </div>
      <InfoText disclosure={info}>
        <p className="text-xs text-ink-3">{t("strategies.leverage.hint")}</p>
      </InfoText>
      <LeverageSlider
        fieldId={ids.field}
        labelId={ids.label}
        text={text}
        handle={handle}
        value={reading.valid ? reading.value : null}
        disabled={readOnly || busy}
        invalid={!reading.valid}
        describedBy={reading.valid ? undefined : ids.problem}
        max={max}
        onText={changeText}
        onHandle={changeStep}
        onStop={changeStep}
        // Save is on the field's row, as wide as its own text needs; the field takes the width that is left.
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
      {max < 20 && reading.valid && <p className="text-xs text-ink-3">{t("strategies.leverage.capNote", { max })}</p>}
      {!reading.valid && (
        <p id={ids.problem} className="text-xs text-loss">
          {t(leverageProblem(reading.refusal, max).key, leverageProblem(reading.refusal, max).values)}
        </p>
      )}
      {save.status === "error" && (
        <p role="alert" className="text-sm text-loss">
          {t(saveRefusal(save.error))}
        </p>
      )}
    </section>
  );
}
