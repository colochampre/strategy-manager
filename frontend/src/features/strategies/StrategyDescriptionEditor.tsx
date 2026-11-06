import { useState } from "react";
import { Save } from "lucide-react";
import { useTranslation } from "react-i18next";

import { DescriptionField } from "@/features/strategies/DescriptionField";
import { readDescription, trimLikeTheServer } from "@/features/strategies/description-value";
import { ApiError } from "@/shared/api/client";
import { useSetStrategyDescription } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";
import { StatusButton } from "@/shared/ui/StatusButton";

interface StrategyDescriptionEditorProps {
  /** Only what it reads. */
  strategy: Pick<Strategy, "id" | "description" | "archived_at">;
}

/** The text of a refused or failed save: the status decides, never the server's wording. */
function saveRefusal(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) return "strategies.description.invalid";
    if (error.status === 409) return "strategies.description.archived";
    if (error.status === 404) return "strategies.description.gone";
  }
  return "strategies.description.saveFailed";
}

/**
 * The author's description of their strategy, with its own Save. The field keeps the text as typed and nothing
 * is sent until Save; the request carries only `description` (the text as typed, or null when it is blank).
 * Save is off while the server would read the text as it already stands, and while it is over the limit.
 */
export function StrategyDescriptionEditor({ strategy }: StrategyDescriptionEditorProps) {
  const { t } = useTranslation();
  const [text, setText] = useState(strategy.description ?? "");
  const [saved, setSaved] = useState(false);
  const save = useSetStrategyDescription(strategy.id);

  const readOnly = strategy.archived_at !== null;
  const reading = readDescription(text);
  const tooLong = !reading.blank && reading.tooLong;
  // What the server would keep, against what it keeps now.
  const kept = reading.blank ? null : trimLikeTheServer(text);
  const changed = kept !== strategy.description;
  const busy = save.isPending;

  // A button that reads "Saved" is disabled, so a save never starts while "Saved" stands. Set on success only.
  const handleSave = () => {
    if (tooLong || !changed || readOnly || busy) return;
    save.mutate(reading.blank ? null : text, { onSuccess: () => setSaved(true) });
  };
  const saveText = t("strategies.description.save");
  const savingText = t("strategies.description.saving");
  const savedText = t("strategies.detail.saved");

  return (
    <section className="flex flex-col gap-3">
      <DescriptionField
        value={text}
        onChange={(next) => {
          setText(next);
          setSaved(false);
        }}
        disabled={readOnly || busy}
      />
      <div className="flex items-start">
        <StatusButton
          texts={[saveText, savingText, savedText]}
          shown={busy ? savingText : saved ? savedText : saveText}
          message={saved ? savedText : null}
          onClick={handleSave}
          disabled={readOnly || busy || tooLong || !changed || saved}
          icon={Save}
          className="min-h-11 rounded-md bg-gain px-3 text-sm font-medium text-ground hover:opacity-90 disabled:opacity-50"
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
