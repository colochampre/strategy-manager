import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { AcceptanceBox, SubmitButton } from "@/features/sign-up/AcceptanceBox";
import { type LegalVersions, useAcceptAgain } from "@/shared/api/me";

/**
 * The acceptance box alone, for a signed-up user once the terms or the policy changed (public-site LS6). It is sent
 * under the versions in force; whatever the server answers, `me` is read again and decides the next screen.
 */
export function AcceptAgainForm({ versions }: { versions: LegalVersions }) {
  const { t } = useTranslation();
  const accept = useAcceptAgain();
  const headingId = useId();
  const [accepts, setAccepts] = useState(false);
  const [failed, setFailed] = useState(false);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!accepts || accept.isPending) return;
    setFailed(false);
    accept.mutate(versions, {
      onSuccess: (result) => {
        if (result.kind === "versionChanged") setAccepts(false);
        setFailed(result.kind !== "accepted" && result.kind !== "incomplete");
      },
      onError: () => setFailed(true),
    });
  };

  return (
    <form aria-labelledby={headingId} onSubmit={submit} noValidate className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <h1 id={headingId} className="font-display text-lg font-semibold text-ink">
          {t("signUp.again.title")}
        </h1>
        <p className="text-sm text-ink-3">{t("signUp.again.body")}</p>
      </div>
      <AcceptanceBox checked={accepts} onChange={setAccepts} />
      {failed && (
        <p role="alert" className="text-sm text-loss">
          {t("signUp.again.failed")}
        </p>
      )}
      <SubmitButton disabled={!accepts || accept.isPending} busy={accept.isPending} />
    </form>
  );
}
