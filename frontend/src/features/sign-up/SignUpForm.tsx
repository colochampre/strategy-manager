import { type FormEvent, type ReactNode, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { AcceptanceBox, SubmitButton, useAcceptance } from "@/features/sign-up/AcceptanceBox";
import { cuitState } from "@/features/sign-up/cuit";
import { type GiveProfileResult, type LegalVersions, type ProfileField, useGiveProfile } from "@/shared/api/me";

const FIELD =
  "min-h-11 w-full min-w-0 rounded-md border border-rule bg-ground px-3 text-sm text-ink focus-visible:outline-2 focus-visible:outline-gain";
const NAME_MAX_LENGTH = 80;
/** The one country served (LS1). The other choice exists only to be told so. */
const SERVED = "AR";
const OTHER = "OTHER";

/** What the form says after a refusal that is not about one field. */
function failureKey(result: GiveProfileResult): string | null {
  switch (result.kind) {
    case "given":
    case "invalid":
      return null;
    case "versionChanged":
      return "signUp.versionChanged";
    case "notServed":
      return "signUp.notServed";
    case "alreadyGiven":
      return "signUp.alreadyGiven";
    default:
      return "signUp.failed";
  }
}

const nameIsWhole = (name: string) => name.trim().length > 0 && name.trim().length <= NAME_MAX_LENGTH;

/**
 * The whole sign-up form (public-site LS2): name, CUIT, country and the three boxes, none ticked. It is sent once,
 * under the versions it shows. A refusal keeps everything typed; a change of the terms unticks only the acceptance.
 */
export function SignUpForm({ versions }: { versions: LegalVersions }) {
  const { t } = useTranslation();
  const give = useGiveProfile();
  const ids = { first: useId(), last: useId(), cuit: useId(), hint: useId(), country: useId() };
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [cuit, setCuit] = useState("");
  const [country, setCountry] = useState("");
  const [adult, setAdult] = useState(false);
  const [truthful, setTruthful] = useState(false);
  const acceptance = useAcceptance(versions);
  const accepts = acceptance.ticked;
  const [refusedField, setRefusedField] = useState<ProfileField | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const cuitIsInvalid = cuitState(cuit) === "invalid" || refusedField === "cuit";
  const notServed = country === OTHER;
  const complete =
    nameIsWhole(firstName) &&
    nameIsWhole(lastName) &&
    cuitState(cuit) === "valid" &&
    country === SERVED &&
    adult &&
    truthful &&
    accepts;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!complete || give.isPending) return;
    setFailure(null);
    give.mutate(
      { firstName, lastName, cuit, country, adult, truthful, accepts, versions },
      {
        onSuccess: (result) => {
          if (result.kind === "invalid") setRefusedField(result.field);
          if (result.kind === "versionChanged") acceptance.clear();
          setFailure(failureKey(result));
        },
        onError: () => setFailure("signUp.failed"),
      },
    );
  };

  const edit = (field: ProfileField, set: (value: string) => void) => (value: string) => {
    set(value);
    if (refusedField === field) setRefusedField(null);
  };

  return (
    <form aria-label={t("signUp.label")} onSubmit={submit} noValidate className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <h1 className="font-display text-lg font-semibold text-ink">{t("signUp.title")}</h1>
        <p className="text-sm text-ink-3">{t("signUp.intro")}</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field id={ids.first} label={t("signUp.firstName")}>
          <input
            id={ids.first}
            value={firstName}
            onChange={(event) => edit("first_name", setFirstName)(event.target.value)}
            autoComplete="given-name"
            maxLength={NAME_MAX_LENGTH}
            aria-invalid={refusedField === "first_name"}
            className={FIELD}
          />
          {refusedField === "first_name" && <FieldError>{t("signUp.nameInvalid")}</FieldError>}
        </Field>
        <Field id={ids.last} label={t("signUp.lastName")}>
          <input
            id={ids.last}
            value={lastName}
            onChange={(event) => edit("last_name", setLastName)(event.target.value)}
            autoComplete="family-name"
            maxLength={NAME_MAX_LENGTH}
            aria-invalid={refusedField === "last_name"}
            className={FIELD}
          />
          {refusedField === "last_name" && <FieldError>{t("signUp.nameInvalid")}</FieldError>}
        </Field>
      </div>

      <Field id={ids.cuit} label={t("signUp.cuit")}>
        <input
          id={ids.cuit}
          value={cuit}
          onChange={(event) => edit("cuit", setCuit)(event.target.value)}
          inputMode="numeric"
          autoComplete="off"
          aria-describedby={ids.hint}
          aria-invalid={cuitIsInvalid}
          className={FIELD}
        />
        <p id={ids.hint} className="text-xs text-ink-3">
          {t("signUp.cuitHint")}
        </p>
        {cuitIsInvalid && <FieldError>{t("signUp.cuitInvalid")}</FieldError>}
      </Field>

      <Field id={ids.country} label={t("signUp.country")}>
        <select
          id={ids.country}
          value={country}
          onChange={(event) => setCountry(event.target.value)}
          className={FIELD}
        >
          <option value="" disabled>
            {t("signUp.countryChoose")}
          </option>
          <option value={SERVED}>{t("signUp.countryAR")}</option>
          <option value={OTHER}>{t("signUp.countryOther")}</option>
        </select>
        {notServed && <FieldError>{t("signUp.notServed")}</FieldError>}
      </Field>

      <div className="flex flex-col gap-3">
        <Declaration label={t("signUp.adult")} checked={adult} onChange={setAdult} />
        <Declaration label={t("signUp.truthful")} checked={truthful} onChange={setTruthful} />
        <AcceptanceBox checked={accepts} onChange={acceptance.set} />
      </div>

      {(failure ?? (acceptance.outdated ? "signUp.versionChanged" : null)) !== null && (
        <p role="alert" className="text-sm text-loss">
          {t(failure ?? "signUp.versionChanged")}
        </p>
      )}
      <SubmitButton disabled={!complete || give.isPending} busy={give.isPending} />
    </form>
  );
}

function Field({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className="text-[13px] text-ink-2">
        {label}
      </label>
      {children}
    </div>
  );
}

function FieldError({ children }: { children: ReactNode }) {
  return <p className="text-xs text-loss">{children}</p>;
}

function Declaration({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="flex items-start gap-3 text-sm text-ink-2">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 size-4 shrink-0 accent-gain"
      />
      <label htmlFor={id}>{label}</label>
    </div>
  );
}
