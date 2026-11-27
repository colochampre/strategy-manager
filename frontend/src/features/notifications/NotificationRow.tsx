import { Lock } from "lucide-react";
import type { ReactNode } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Link } from "react-router";

import { describeItem, type SentencePart } from "@/features/notifications/describe";
import { OriginDot } from "@/features/positions/PositionMark";
import type { NotificationItem, NotificationKind } from "@/shared/api/notifications";
import { Masked } from "@/shared/hidden/Masked";
import { cn } from "@/shared/lib/cn";
import { clockText } from "@/shared/lib/figure-text";
import { PILL } from "@/shared/ui/Pill";

interface KindLook {
  /** The 3 px bar on the item's left edge. */
  edge: string;
  icon: string;
  pill: string;
  /** The chip's dot. */
  dot: string;
}

/** Each kind reads its own notification tokens (RD.0); no other colour reaches an item but the amber dot of a rehearsal. */
export const KIND_LOOK: Readonly<Record<NotificationKind, KindLook>> = {
  OPERATION: {
    edge: "border-l-notif-operation",
    icon: "text-notif-operation",
    pill: "border-notif-operation/40 bg-notif-operation-soft text-notif-operation-ink",
    dot: "bg-notif-operation",
  },
  SAFETY: {
    edge: "border-l-notif-safety",
    icon: "text-notif-safety",
    pill: "border-notif-safety/40 bg-notif-safety-soft text-notif-safety-ink",
    dot: "bg-notif-safety",
  },
  NOTICE: {
    edge: "border-l-notif-notice",
    icon: "text-notif-notice",
    pill: "border-notif-notice/40 bg-notif-notice-soft text-notif-notice-ink",
    dot: "bg-notif-notice",
  },
  DISCREPANCY: {
    edge: "border-l-notif-discrepancy",
    icon: "text-notif-discrepancy",
    pill: "border-notif-discrepancy/40 bg-notif-discrepancy-soft text-notif-discrepancy-ink",
    dot: "bg-notif-discrepancy",
  },
};

function Figure({ children }: { children?: ReactNode }) {
  return <span className="font-mono tabular-nums text-ink">{children}</span>;
}

function MaskedFigure({ children }: { children?: ReactNode }) {
  return (
    <Figure>
      <Masked>{children}</Masked>
    </Figure>
  );
}

/** The pair of an operation; a rehearsal carries the amber dot beside it, as in My trades. */
function PairFigure({ rehearsal, children }: { rehearsal: boolean; children?: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1">
      {rehearsal && <OriginDot origin="rehearsal" />}
      <Figure>{children}</Figure>
    </span>
  );
}

function Sentence({ part, rehearsal }: { part: SentencePart; rehearsal: boolean }) {
  return (
    <Trans
      i18nKey={`notifications.sentence.${part.key}`}
      values={part.values}
      components={{
        num: <Figure />,
        fig: <MaskedFigure />,
        pair: <PairFigure rehearsal={rehearsal} />,
        pnl: <PnlFigure tone={part.pnlTone ?? ""} />,
      }}
    />
  );
}

function PnlFigure({ tone, children }: { tone: string; children?: ReactNode }) {
  return (
    <span className={cn("font-mono tabular-nums", tone)}>
      <Masked>{children}</Masked>
    </span>
  );
}

/**
 * One item of the feed as ex5 draws it: the kind's edge and icon, the title, one sentence, and on the right the kind's
 * pill, the time and, where one fixes it, a link. A rehearsal carries the amber dot by its pair, as in My trades.
 */
export function NotificationRow({ item }: { item: NotificationItem }) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? "en";
  const look = KIND_LOOK[item.kind];
  const description = describeItem(item, t, i18n, locale);
  const Icon = description.icon;
  return (
    <li
      data-testid="notification"
      data-kind={item.kind}
      className={cn(
        "flex gap-3.5 border-b border-l-[3px] border-b-rule-soft py-4 pr-5 pl-[17px] last:border-b-0",
        look.edge,
      )}
    >
      <Icon aria-hidden="true" className={cn("mt-0.5 size-4 shrink-0", description.iconTone ?? look.icon)} />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-ink">{t(`notifications.title.${description.titleKey}`, description.titleValues)}</p>
        <p className="mt-0.5 max-w-[640px] text-ink-2">
          {description.sentence.map((part, index) => (
            <span key={part.key}>
              {index > 0 && " "}
              <Sentence part={part} rehearsal={item.rehearsal} />
            </span>
          ))}
        </p>
        {item.kind === "DISCREPANCY" && (
          <p className="mt-1.5 flex items-center gap-1.5 text-xs text-ink-3">
            <Lock aria-hidden="true" className="size-3" />
            {t("notifications.adminOnly")}
          </p>
        )}
      </div>
      <div className="flex flex-col items-end gap-2 text-[12.5px] text-ink-3">
        <span className={cn(PILL, look.pill)}>{t(`notifications.pill.${item.kind}`)}</span>
        <span className="font-mono tabular-nums">{clockText(item.occurred_at) ?? t("trades.noValue")}</span>
        {description.link !== null && (
          <Link to={description.link.to} className="text-gain hover:text-gain-bright">
            {t(description.link.labelKey)}
          </Link>
        )}
      </div>
    </li>
  );
}
