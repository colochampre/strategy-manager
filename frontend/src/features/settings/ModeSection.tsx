import { FlaskConical, Zap } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type ChangeModeResult, type Mode, useChangeMode, useMe } from "@/shared/api/me";
import { ModeDialog } from "@/shared/layout/ModeDialog";
import { Card, CARD_ROW } from "@/shared/ui/Card";
import { Segmented } from "@/shared/ui/Segmented";

const ICON = "size-4 shrink-0";

/**
 * The mode's switch (S7, rewritten by L12): the badge at the top of the panel only shows the mode, and it is changed
 * here, from Mi cuenta (ex7). Every rule of the old drop-down stays:
 *
 * - nothing is sent on the press that opens the confirmation; the request goes from the dialog's own button;
 * - the refusals are said in the dialog, in the panel's words, never the server's;
 * - with the server's brake on, the switch is locked on simulation and says why, whatever the user's own mode is;
 * - while the mode is not known (asked, or the read failed) there is no switch, so "live" is never guessed.
 *
 * The dialog stands apart from the switch, so a refusal stays on screen when the read it triggered locks the switch.
 */
export function ModeSection() {
  const { t } = useTranslation();
  const me = useMe();
  const change = useChangeMode();
  const [target, setTarget] = useState<Mode | null>(null);
  const [result, setResult] = useState<ChangeModeResult | null>(null);

  const open = (mode: Mode) => {
    setResult(null);
    setTarget(mode);
  };

  const confirm = () => {
    if (target === null) return;
    change.mutate(target, {
      onSuccess: (outcome) => {
        if (outcome.kind === "changed") setTarget(null);
        else setResult(outcome);
      },
    });
  };

  const body = (() => {
    if (me.isError) return <p className="text-[15px] text-ink-3">{t("status.unknown")}</p>;
    if (me.data === undefined) return <p className="text-[15px] text-ink-3">{t("status.checking")}</p>;
    const brake = me.data.dryRunBrake;
    return (
      <div className={CARD_ROW}>
        <div className="flex min-w-0 flex-col gap-1">
          <p className="max-w-[60ch] text-[15px] text-ink">{t("settings.mode.description")}</p>
          {brake && <p className="max-w-[60ch] text-[13px] text-ink-2">{t("settings.mode.forced")}</p>}
        </div>
        <Segmented
          label={t("settings.mode.group")}
          value={brake ? "SIMULATION" : me.data.mode}
          disabled={brake}
          onChange={open}
          options={[
            { value: "LIVE", label: t("status.live"), icon: <Zap aria-hidden="true" className={`${ICON} text-gain`} /> },
            {
              value: "SIMULATION",
              label: t("status.simulation"),
              icon: <FlaskConical aria-hidden="true" className={ICON} />,
            },
          ]}
        />
      </div>
    );
  })();

  return (
    <>
      <Card title={t("settings.mode.title")}>{body}</Card>
      {target !== null && (
        <ModeDialog
          target={target}
          pending={change.isPending}
          result={result}
          onConfirm={confirm}
          onCancel={() => setTarget(null)}
        />
      )}
    </>
  );
}
