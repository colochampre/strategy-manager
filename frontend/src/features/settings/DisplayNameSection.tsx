import { Save } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { useChooseDisplayName, useMe, type ChooseDisplayNameResult } from "@/shared/api/me";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";
import { ReportSection } from "@/shared/ui/ReportSection";
import { StatusButton } from "@/shared/ui/StatusButton";

const FIELD =
  "min-h-11 min-w-0 flex-1 rounded-md border border-rule bg-ground px-3 text-sm text-ink focus-visible:outline-2 focus-visible:outline-gain";

function refusalKey(result: ChooseDisplayNameResult | undefined): string | null {
  switch (result?.kind) {
    case "taken":
      return "settings.name.taken";
    case "invalid":
      return "settings.name.invalid";
    case "unknown":
    case "unauthorized":
      return "settings.name.failed";
    default:
      return null;
  }
}

/**
 * The user's public name (decision 27). The draft holds only what is being typed: with none, the field shows the
 * stored name, so a saved name reads as the server normalized it. A refusal keeps what was typed, to be corrected.
 */
export function DisplayNameSection() {
  const { t } = useTranslation();
  const me = useMe().data;
  const choose = useChooseDisplayName();
  const [draft, setDraft] = useState<string | null>(null);
  const info = useInfoDisclosure();
  const headingId = useId();
  const fieldId = useId();

  if (me === undefined) return null;

  const stored = me.displayName;
  const value = draft ?? stored ?? "";
  const canSave = value.trim() !== "" && value.trim() !== stored && !choose.isPending;
  const saved = choose.data?.kind === "chosen";
  const refusal = refusalKey(choose.data);
  const saveText = t("settings.name.save");
  const savingText = t("settings.name.saving");
  const savedText = t("settings.name.saved");

  const edit = (next: string) => {
    setDraft(next);
    choose.reset();
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!canSave) return;
    choose.mutate(value, {
      onSuccess: (result) => {
        if (result.kind === "chosen") setDraft(null);
      },
    });
  };

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center">
          <h2 id={headingId} className="font-display text-base font-semibold text-ink">
            {t("settings.profile.title")}
          </h2>
          <InfoButton disclosure={info} label={t("settings.name.info")} />
        </div>
        <InfoText disclosure={info}>
          <p className="text-xs text-ink-3">{t("settings.name.intro")}</p>
          <p className="text-xs text-ink-3">{t("settings.name.hint")}</p>
          {stored === null && <p className="text-xs text-ink-3">{t("settings.name.missing")}</p>}
        </InfoText>
      </div>
      <ReportSection>
        <div className="flex flex-col gap-3">
          <form onSubmit={submit} noValidate className="flex flex-col gap-1.5">
            <label htmlFor={fieldId} className="text-[13px] text-ink-2">
              {t("settings.name.label")}
            </label>
            <div className="flex items-center gap-2">
              <input
                id={fieldId}
                type="text"
                value={value}
                onChange={(event) => edit(event.target.value)}
                autoComplete="off"
                aria-describedby={info.textId}
                className={FIELD}
              />
              <StatusButton
                texts={[saveText, savingText, savedText]}
                shown={choose.isPending ? savingText : saved ? savedText : saveText}
                message={saved ? savedText : null}
                submit
                disabled={!canSave}
                icon={Save}
                iconOnly
                busy={choose.isPending}
                look="primary"
              />
            </div>
          </form>
          {refusal !== null && (
            <p role="alert" className="text-sm text-loss">
              {t(refusal)}
            </p>
          )}
        </div>
      </ReportSection>
    </section>
  );
}
