import { Save } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { formatCuit } from "@/features/sign-up/cuit";
import { useCorrectName, useMe, type CorrectNameResult } from "@/shared/api/me";
import { LEGAL_CONTACT } from "@/shared/legal/LegalDocument";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";
import { ReportSection } from "@/shared/ui/ReportSection";
import { StatusButton } from "@/shared/ui/StatusButton";

const FIELD =
  "min-h-11 w-full min-w-0 rounded-md border border-rule bg-ground px-3 text-sm text-ink focus-visible:outline-2 focus-visible:outline-gain";
const NAME_MAX_LENGTH = 80;

function failureKey(result: CorrectNameResult | undefined): string | null {
  return result?.kind === "unknown" || result?.kind === "unauthorized" ? "settings.identity.failed" : null;
}

/**
 * What the user gave at sign-up (public-site LS2), for them to check. First and last name can be corrected here
 * (Ley 25.326 art. 16; the terms ask them to be kept up to date). The CUIT and the country only read: the CUIT names
 * whose trades they are, so a correction goes through the contact address. Drafts hold only what is being typed:
 * with none, a field shows the stored name, so a saved name reads as the server normalized it.
 */
export function IdentitySection() {
  const { t } = useTranslation();
  const me = useMe().data;
  const correct = useCorrectName();
  const [firstDraft, setFirstDraft] = useState<string | null>(null);
  const [lastDraft, setLastDraft] = useState<string | null>(null);
  const info = useInfoDisclosure();
  const ids = { heading: useId(), first: useId(), last: useId() };

  const profile = me?.profile;
  if (profile === undefined || profile === null) return null;

  const first = firstDraft ?? profile.firstName;
  const last = lastDraft ?? profile.lastName;
  const whole = (name: string) => name.trim() !== "";
  const changed = first !== profile.firstName || last !== profile.lastName;
  const canSave = whole(first) && whole(last) && changed && !correct.isPending;
  const saved = correct.data?.kind === "corrected";
  const refused = correct.data?.kind === "invalid" ? correct.data.field : null;
  const failure = failureKey(correct.data);
  const texts = [t("settings.identity.save"), t("settings.identity.saving"), t("settings.identity.saved")] as const;

  const edit = (set: (value: string) => void) => (value: string) => {
    set(value);
    correct.reset();
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!canSave) return;
    correct.mutate(
      { firstName: first, lastName: last },
      {
        onSuccess: (result) => {
          if (result.kind !== "corrected") return;
          setFirstDraft(null);
          setLastDraft(null);
        },
      },
    );
  };

  return (
    <section aria-labelledby={ids.heading} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center">
          <h2 id={ids.heading} className="font-display text-base font-semibold text-ink">
            {t("settings.identity.title")}
          </h2>
          <InfoButton disclosure={info} label={t("settings.identity.info")} />
        </div>
        <InfoText disclosure={info}>
          <p className="text-xs text-ink-3">{t("settings.identity.intro")}</p>
        </InfoText>
      </div>
      <ReportSection>
        <form onSubmit={submit} noValidate className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <NameField
              id={ids.first}
              label={t("signUp.firstName")}
              value={first}
              onChange={edit(setFirstDraft)}
              autoComplete="given-name"
              refused={refused === "first_name"}
              refusal={t("signUp.nameInvalid")}
            />
            <NameField
              id={ids.last}
              label={t("signUp.lastName")}
              value={last}
              onChange={edit(setLastDraft)}
              autoComplete="family-name"
              refused={refused === "last_name"}
              refusal={t("signUp.nameInvalid")}
            />
          </div>
          <dl className="grid gap-4 sm:grid-cols-2">
            <div className="flex min-w-0 flex-col gap-1.5">
              <dt className="text-[13px] text-ink-2">{t("signUp.cuit")}</dt>
              <dd className="text-sm text-ink tabular-nums">{formatCuit(profile.cuit)}</dd>
            </div>
            <div className="flex min-w-0 flex-col gap-1.5">
              <dt className="text-[13px] text-ink-2">{t("signUp.country")}</dt>
              <dd className="text-sm text-ink">{t("signUp.countryAR")}</dd>
            </div>
          </dl>
          <p className="text-xs text-ink-3">{t("settings.identity.fixed", { contact: LEGAL_CONTACT })}</p>
          {failure !== null && (
            <p role="alert" className="text-sm text-loss">
              {t(failure)}
            </p>
          )}
          <div className="flex justify-end">
            <StatusButton
              texts={texts}
              shown={correct.isPending ? texts[1] : saved ? texts[2] : texts[0]}
              message={saved ? texts[2] : null}
              submit
              disabled={!canSave}
              icon={Save}
              className="min-h-11 rounded-lg bg-gain px-3 text-sm font-medium text-ground hover:opacity-90 disabled:opacity-50"
            />
          </div>
        </form>
      </ReportSection>
    </section>
  );
}

interface NameFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
  refused: boolean;
  refusal: string;
}

function NameField({ id, label, value, onChange, autoComplete, refused, refusal }: NameFieldProps) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className="text-[13px] text-ink-2">
        {label}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete={autoComplete}
        maxLength={NAME_MAX_LENGTH}
        aria-invalid={refused}
        className={FIELD}
      />
      {refused && <p className="text-xs text-loss">{refusal}</p>}
    </div>
  );
}
