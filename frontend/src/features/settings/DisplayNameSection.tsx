import { Save } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { useChooseDisplayName, useMe, type ChooseDisplayNameResult } from "@/shared/api/me";
import { StatusButton } from "@/shared/ui/StatusButton";

const FIELD =
  "min-h-11 w-full max-w-sm rounded-md border border-rule bg-ground px-3 text-sm text-ink focus-visible:outline-2 focus-visible:outline-gain";
const SAVE =
  "min-h-11 rounded-md border border-gain bg-gain px-3.5 text-sm font-medium text-ground disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain";

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
  const headingId = useId();
  const hintId = useId();

  if (me === undefined) return null;

  const stored = me.displayName;
  const value = draft ?? stored ?? "";
  const canSave = value.trim() !== "" && value.trim() !== stored && !choose.isPending;
  const refusal = refusalKey(choose.data);

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
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h2 id={headingId} className="font-display text-lg font-semibold text-ink">
        {t("settings.name.title")}
      </h2>
      <p className="max-w-[78ch] text-sm text-ink-2">{t("settings.name.intro")}</p>
      {stored === null && <p className="max-w-[78ch] text-sm text-ink-2">{t("settings.name.missing")}</p>}
      <form onSubmit={submit} noValidate className="flex flex-col gap-2">
        <label className="flex flex-col gap-1 text-[13px] text-ink-2">
          {t("settings.name.label")}
          <input
            type="text"
            value={value}
            onChange={(event) => edit(event.target.value)}
            autoComplete="off"
            aria-describedby={hintId}
            className={FIELD}
          />
        </label>
        <p id={hintId} className="max-w-[78ch] text-[13px] text-ink-3">
          {t("settings.name.hint")}
        </p>
        <div>
          <StatusButton
            texts={[t("settings.name.save"), t("settings.name.saving")]}
            shown={choose.isPending ? t("settings.name.saving") : t("settings.name.save")}
            message={choose.data?.kind === "chosen" ? t("settings.name.saved") : null}
            submit
            disabled={!canSave}
            icon={Save}
            className={SAVE}
          />
        </div>
      </form>
      {refusal !== null && (
        <p role="alert" className="text-sm text-loss">
          {t(refusal)}
        </p>
      )}
    </section>
  );
}
