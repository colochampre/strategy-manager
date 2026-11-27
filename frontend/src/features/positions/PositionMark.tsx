import { TriangleAlert } from "lucide-react";
import { useId, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode, SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";

import { JoinedParts, useVenueParts } from "@/features/positions/MarkLine";
import { ORIGIN_STYLE } from "@/features/positions/origin";
import type { Origin } from "@/features/positions/origin";
import type { OpenPosition, VenueDisagreement } from "@/shared/api/positions";
import { cn } from "@/shared/lib/cn";
import { Tooltip } from "@/shared/ui/Tooltip";

type Translate = ReturnType<typeof useTranslation>["t"];

/** The reason a position's figures are missing: its own text for the three codes the server names, the generic one for any other. */
export function reasonText(code: string, t: Translate): string {
  return t(code === "UNRESOLVED_SYMBOL" || code === "SEVERAL_MARKETS" || code === "FLIPPED" ? `positions.reason.${code}` : "positions.reason.other");
}

/** The slot both marks fill, so that a symbol starts at the same place whether its row has a dot or a sign. */
const SLOT = "-ml-1 inline-flex size-4.5 shrink-0 items-center justify-center";

/**
 * The origin as a round dot in its token, named by its word and told in a tooltip. `label` names it more
 * precisely where the row knows more (a closed trade's dry-run tag says how it was filled, L31).
 */
export function OriginDot({ origin, label }: { origin: Origin; label?: string }) {
  const { t } = useTranslation();
  const look = ORIGIN_STYLE[origin];
  const word = label ?? t(look.textKey);
  return (
    // The tip repeats the name, so it does not also describe the trigger: a screen reader would read it twice.
    <Tooltip text={word} describes={false} className="-ml-1 inline-flex">
      <span role="img" aria-label={word} className="inline-flex size-4.5 items-center justify-center">
        {/* The mode badge's dot (`shared/layout/ModeBadge.tsx`). */}
        <i data-dot="true" aria-hidden="true" className={cn("size-[7px] shrink-0 rounded-full", look.dot)} />
      </span>
    </Tooltip>
  );
}

interface SignDialogProps {
  groupName: string;
  position: OpenPosition;
  children: ReactNode;
  onClose: () => void;
}

/**
 * The sign's full message, in a native modal `<dialog>` (as `DeleteKeyDialog` is). Nothing is positioned by
 * script: the browser centres a modal in the top layer, so the panel's CSP needs no inline style. Escape and the
 * browser's own `cancel` event are routed to one handler. A dialog inherits `white-space` and `text-align` from
 * its DOM ancestor, here a table cell, hence `whitespace-normal break-words text-left`.
 */
function SignDialog({ groupName, position, children, onClose }: SignDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null) return undefined;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    closeRef.current?.focus();
    return () => {
      if (typeof dialog.close === "function") dialog.close();
    };
  }, []);

  const handleKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    onClose();
  };

  const handleCancel = (event: SyntheticEvent<HTMLDialogElement>) => {
    event.preventDefault();
    onClose();
  };

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      onKeyDown={handleKeyDown}
      onCancel={handleCancel}
      // The dialog sits inside a table row: a click in it is not a click on the row.
      onClick={(event) => event.stopPropagation()}
      className="fixed inset-0 m-auto w-[calc(100%-2rem)] max-w-lg rounded-lg whitespace-normal break-words text-left border border-rule bg-panel p-0 text-ink backdrop:bg-ground/80 motion-safe:animate-dialog-in"
    >
      <div className="flex flex-col gap-3 p-6 font-sans text-sm font-normal">
        <h2 id={titleId} className="text-sm font-semibold text-ink">
          {groupName}
        </h2>
        <div className="flex flex-col gap-1 font-mono text-xs">{children}</div>
        <p className="text-xs text-ink-2">{t("positions.sign.origin", { origin: t(ORIGIN_STYLE[position.origin].textKey) })}</p>
        <div className="flex justify-end">
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className="min-h-11 rounded-lg border border-rule px-3.5 text-sm text-ink-2 hover:bg-panel-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gain"
          >
            {t("positions.sign.close")}
          </button>
        </div>
      </div>
    </dialog>
  );
}

/**
 * The warning sign: a button. Hover and keyboard focus show a one-line tooltip (the summary and the origin);
 * a click, a tap, Enter or Space opens the whole message in a modal dialog, because a link may be inside it and
 * a tooltip cannot hold one. Closing the dialog returns the focus to the sign.
 */
function SignShell({
  position,
  groupName,
  summary,
  children,
}: {
  position: OpenPosition;
  groupName: string;
  summary: string;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const button = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const pair = position.markets.join(" / ");
  const tip = `${summary} · ${t(ORIGIN_STYLE[position.origin].textKey)}`;

  const close = () => {
    setOpen(false);
    button.current?.focus();
  };

  return (
    <Tooltip text={tip} tabbable={false} className="inline-flex">
      <button
        ref={button}
        type="button"
        aria-label={t("positions.sign.name", { pair })}
        aria-haspopup="dialog"
        className={cn(SLOT, "rounded-sm text-loss focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-gain")}
        onClick={() => setOpen(true)}
      >
        <TriangleAlert aria-hidden="true" className="size-4 text-loss" />
      </button>
      {open && (
        <SignDialog groupName={groupName} position={position} onClose={close}>
          {children}
        </SignDialog>
      )}
    </Tooltip>
  );
}

function Reason({ position }: { position: OpenPosition }) {
  const { t } = useTranslation();
  if (position.figures_missing === null) return null;
  return <p className="font-sans">{reasonText(position.figures_missing, t)}</p>;
}

function VenueSign({ position, disagreement, asOf }: { position: OpenPosition; disagreement: VenueDisagreement; asOf: string }) {
  const { t } = useTranslation();
  const parts = useVenueParts(position, disagreement, asOf);
  return (
    <SignShell
      position={position}
      groupName={t("positions.venue.groupName", { pair: position.markets.join(" / ") })}
      summary={t("positions.venue.disagrees")}
    >
      <div className="flex flex-wrap items-center gap-y-0.5">
        <JoinedParts parts={parts} />
      </div>
      <Reason position={position} />
    </SignShell>
  );
}

/**
 * What stands beside a position's symbol (RD.3d, L17): the origin as a round dot, or, for a position the venue
 * disagrees with or whose figures are missing, a warning sign in its place. The sign's message carries what the
 * rows under the position used to say, and the origin, so nothing the old rows said is lost.
 */
export function PositionMark({ position, asOf }: { position: OpenPosition; asOf: string }) {
  const { t } = useTranslation();
  if (position.venue_disagreement !== null) {
    return <VenueSign position={position} disagreement={position.venue_disagreement} asOf={asOf} />;
  }
  if (position.figures_missing !== null) {
    return (
      <SignShell
        position={position}
        groupName={t("positions.sign.name", { pair: position.markets.join(" / ") })}
        // The tooltip says what is missing in a few words; the reason, which can be long, is in the dialog (L18).
        summary={t("positions.sign.figuresMissing")}
      >
        <Reason position={position} />
      </SignShell>
    );
  }
  return <OriginDot origin={position.origin} />;
}
