import { useState } from "react";
import { Save } from "lucide-react";
import { useTranslation } from "react-i18next";

import { StopLevelField } from "@/features/strategies/StopLevelField";
import { readStopLevel } from "@/features/strategies/stop-level";
import { ApiError } from "@/shared/api/client";
import { useSetStrategyStopLevel } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";
import { StatusButton } from "@/shared/ui/StatusButton";

interface StopLevelEditorProps {
  /** Only what it reads. */
  strategy: Pick<Strategy, "id" | "stop_loss_pct" | "archived_at">;
}

/** The text of a refused or failed save: the status decides, never the server's wording. */
function saveRefusal(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) return "strategies.stopLevel.invalid";
    if (error.status === 409) return "strategies.stopLevel.archived";
    if (error.status === 404) return "strategies.stopLevel.gone";
  }
  return "strategies.stopLevel.saveFailed";
}

/** What the server holds as a typed level reads, so "10.00" and "10" are the same level and Save stays off. */
function sameLevel(typed: string, stored: string): boolean {
  const storedReading = readStopLevel(stored);
  const reading = readStopLevel(typed);
  return reading.valid && storedReading.valid && reading.canonical === storedReading.canonical;
}

/**
 * The author's stop level for their strategy, with its own Save. The field keeps the text as typed and nothing
 * is sent until Save; the request carries only `stop_loss_pct`. A change applies to openings made after it.
 */
export function StopLevelEditor({ strategy }: StopLevelEditorProps) {
  const { t } = useTranslation();
  const [text, setText] = useState(() => {
    const stored = readStopLevel(strategy.stop_loss_pct);
    return stored.valid ? stored.canonical : "";
  });
  const [saved, setSaved] = useState(false);
  const save = useSetStrategyStopLevel(strategy.id);

  const readOnly = strategy.archived_at !== null;
  const reading = readStopLevel(text);
  const changed = reading.valid && !sameLevel(text, strategy.stop_loss_pct);
  const busy = save.isPending;

  // A button that reads "Saved" is disabled, so a save never starts while "Saved" stands. Set on success only.
  const handleSave = () => {
    if (!reading.valid || !changed || readOnly || busy) return;
    save.mutate(reading.canonical, { onSuccess: () => setSaved(true) });
  };
  const saveText = t("strategies.stopLevel.save");
  const savingText = t("strategies.stopLevel.saving");
  const savedText = t("strategies.detail.saved");

  return (
    // Named, so this Save is told apart from the other editors' Save, which say the same one word.
    <section aria-label={t("strategies.stopLevel.label")} className="flex flex-col gap-3">
      <StopLevelField
        value={text}
        onChange={(next) => {
          setText(next);
          setSaved(false);
        }}
        disabled={readOnly || busy}
      />
      <div className="flex items-start justify-end">
        <StatusButton
          texts={[saveText, savingText, savedText]}
          shown={busy ? savingText : saved ? savedText : saveText}
          message={saved ? savedText : null}
          onClick={handleSave}
          disabled={readOnly || busy || !reading.valid || !changed || saved}
          icon={Save}
          iconOnly
          busy={busy}
          look="primary"
        />
      </div>
      {save.status === "error" && (
        <p role="alert" className="text-sm text-loss">
          {t(saveRefusal(save.error))}
        </p>
      )}
    </section>
  );
}
