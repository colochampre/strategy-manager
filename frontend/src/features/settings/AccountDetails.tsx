import { Info, Lock, Pencil, X } from "lucide-react";
import { type ReactNode, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { DisplayNameSection } from "@/features/settings/DisplayNameSection";
import { IdentitySection } from "@/features/settings/IdentitySection";
import { formatCuit } from "@/features/sign-up/cuit";
import { useMe } from "@/shared/api/me";
import { cn } from "@/shared/lib/cn";
import { Card, CARD_ROW } from "@/shared/ui/Card";

interface FactProps {
  label: string;
  /** Mono for a figure (the CUIT). */
  mono?: boolean;
  /** The fact cannot be changed from the panel: a lock closes its row. */
  locked?: boolean;
  children: ReactNode;
}

/** One line of the card (ex7 `.row`): the label over the value, the lock on the right when it cannot be changed. */
function Fact({ label, mono = false, locked = false, children }: FactProps) {
  const { t } = useTranslation();
  return (
    <div className={CARD_ROW}>
      <div className="min-w-0">
        <small className="mb-0.5 block text-[12.5px] text-ink-3">{label}</small>
        <span className={cn("block text-[15px] text-ink", mono && "font-mono tabular-nums")}>{children}</span>
      </div>
      {locked && (
        <Lock role="img" aria-label={t("settings.details.locked")} className="size-[18px] shrink-0 text-ink-3" />
      )}
    </div>
  );
}

/**
 * Sus datos (ex7): what the panel knows of the person, read. The display name and the name can be changed, so the
 * card's action opens the two forms that already do it (`DisplayNameSection`, `IdentitySection`, with every rule
 * they enforce) under the card; the CUIT and the country only read, each with a lock and the note that says why.
 */
export function AccountDetails() {
  const { t } = useTranslation();
  const me = useMe().data;
  const [editing, setEditing] = useState(false);
  const formsId = useId();

  if (me === undefined) return null;
  const profile = me.profile;

  const action = (
    <button
      type="button"
      aria-expanded={editing}
      aria-controls={formsId}
      onClick={() => setEditing((open) => !open)}
      className="inline-flex h-[30px] items-center gap-2 rounded-lg border border-rule-strong bg-panel-2 px-[11px] text-[13px] font-medium text-ink transition-colors hover:bg-panel motion-reduce:transition-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain"
    >
      {editing ? <X aria-hidden="true" className="size-4" /> : <Pencil aria-hidden="true" className="size-4" />}
      {editing ? t("settings.details.closeEdit") : t("settings.details.editName")}
    </button>
  );

  return (
    <>
      <Card title={t("settings.details.title")} action={action}>
        <Fact label={t("settings.details.displayName")}>{me.displayName ?? t("settings.details.none")}</Fact>
        {profile !== null && (
          <>
            <Fact label={t("settings.details.name")}>{`${profile.firstName} ${profile.lastName}`}</Fact>
            <Fact label={t("signUp.cuit")} mono locked>
              {formatCuit(profile.cuit)}
            </Fact>
            <Fact label={t("signUp.country")} locked>
              {t("signUp.countryAR")}
            </Fact>
            <div className="mt-4 flex items-center gap-2 text-[13px] text-ink-3">
              <Info aria-hidden="true" className="size-4 shrink-0" />
              {t("settings.details.note")}
            </div>
          </>
        )}
      </Card>
      {editing && (
        <div id={formsId} className="flex flex-col gap-4">
          <DisplayNameSection />
          <IdentitySection />
        </div>
      )}
    </>
  );
}
