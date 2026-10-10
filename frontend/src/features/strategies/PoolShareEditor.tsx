import { useId } from "react";
import { useTranslation } from "react-i18next";

import { ShareSlider } from "@/features/strategies/ShareSlider";
import { readStored, roundToHandle } from "@/features/strategies/share-value";
import type { Strategy } from "@/shared/api/types";

interface PoolShareEditorProps {
  strategy: Strategy;
}

export function PoolShareEditor({ strategy }: PoolShareEditorProps) {
  const { t } = useTranslation();
  const ids = { field: useId(), label: useId() };
  const stored = readStored(strategy.allocation_percent) ?? "";

  return (
    <section className="flex flex-col gap-3">
      <label id={ids.label} htmlFor={ids.field} className="text-sm text-ink-2">
        {t("strategies.detail.share.label")}
      </label>
      <ShareSlider
        fieldId={ids.field}
        labelId={ids.label}
        text={stored}
        handle={roundToHandle(stored)}
        value={stored}
        disabled={false}
        invalid={false}
        onText={() => undefined}
        onHandle={() => undefined}
        onStop={() => undefined}
      />
      <button type="button" className="min-h-11 rounded-md bg-gain px-3 text-sm font-medium text-ground">
        {t("strategies.detail.share.save")}
      </button>
    </section>
  );
}
