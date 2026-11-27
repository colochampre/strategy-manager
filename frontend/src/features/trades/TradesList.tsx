import { Shield, ShieldAlert, User } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { PositionMark, OriginDot } from "@/features/positions/PositionMark";
import { placementOf, type TipPlacement } from "@/features/strategies/StrategyTableCells";
import { currencyOf, exchangeOf, openedAtOf, pairOf, sideOf, strategyOf, type TradeLine } from "@/features/trades/lines";
import type { CloseCause } from "@/shared/api/trades";
import { exchangeName } from "@/shared/exchanges/exchange-name";
import { Masked } from "@/shared/hidden/Masked";
import { useIsWide } from "@/shared/layout/useIsWide";
import { useTableFits } from "@/shared/layout/useTableFits";
import { amountText, parseDecimal, toneClass } from "@/shared/lib/amount-text";
import { cn } from "@/shared/lib/cn";
import { tableFigureText } from "@/shared/lib/figure-text";
import { Instant } from "@/shared/ui/Instant";
import { Pill } from "@/shared/ui/Pill";
import { TABLE_CELL, TABLE_HEAD } from "@/shared/ui/table-styles";
import { Tooltip } from "@/shared/ui/Tooltip";

/** Tailwind's `md`: the width from which the operations can be a table at all. */
const MD_QUERY = "(min-width: 768px)";

/** Nine columns take the Users table's 8 px sides at the same 13 px, so the table fits the page's column. */
const SIDES = "px-2 first:pl-3.5 last:pr-3";
const FIGURE = "text-right font-mono tabular-nums text-ink-2";
const LABEL = "text-[10px] uppercase tracking-[0.09em] text-ink-3";

interface CloseMarkLook {
  icon: LucideIcon;
  tone: string;
}

/** Every close mark is of the stop's shield family; the person is the user's own close (L53, L54). */
const CLOSE_MARKS: Readonly<Record<Exclude<CloseCause, "SIGNAL">, CloseMarkLook>> = {
  STOP_FIRED: { icon: Shield, tone: "text-loss" },
  STOP_FAILED_CLOSED: { icon: ShieldAlert, tone: "text-loss" },
  STRATEGY_STOPPED_CLOSED: { icon: ShieldAlert, tone: "text-loss" },
  MANUAL_CLOSE: { icon: User, tone: "text-ink-3" },
};

/** The slot of the mark left of a close time: 14 px wide whether it holds a mark or not, so the times line up. */
function CloseSlot({ cause, placement }: { cause: CloseCause | null; placement: TipPlacement }) {
  const { t } = useTranslation();
  const look = cause === null || cause === "SIGNAL" ? null : CLOSE_MARKS[cause];
  const text = look === null || cause === null || cause === "SIGNAL" ? "" : t(`trades.close.${cause}`);
  return (
    <span data-testid="my-trade-close-slot" className="inline-flex w-3.5 shrink-0 justify-center">
      {look !== null && (
        // The tip repeats the name, so it does not also describe the trigger.
        <Tooltip text={text} describes={false} placement={placement}>
          <span role="img" aria-label={text} data-testid="my-trade-close-mark" className={cn("inline-flex", look.tone)}>
            <look.icon aria-hidden="true" className="size-3.5" />
          </span>
        </Tooltip>
      )}
    </span>
  );
}

/** The name's widest: a longer one is cut with an ellipsis, so it cannot push the table into cards (L56). */
const NAME = "block max-w-44 truncate font-sans";

/**
 * The strategy's name, a link to the page the server says this user can open, plain text when there is none. A cut
 * name is told whole in a tip; one that fits has none. It is measured again once the web fonts load, since the
 * fallback face is another width (L51).
 */
function StrategyName({ line, placement }: { line: TradeLine; placement: TipPlacement }) {
  const { name, href } = strategyOf(line);
  const ref = useRef<HTMLElement | null>(null);
  const [cut, setCut] = useState(false);
  useLayoutEffect(() => {
    const measure = () => {
      const element = ref.current;
      if (element !== null) setCut(element.scrollWidth > element.clientWidth);
    };
    measure();
    const fonts = typeof document === "undefined" ? undefined : document.fonts;
    if (fonts === undefined) return undefined;
    let live = true;
    void fonts.ready.then(() => {
      if (live) measure();
    });
    return () => {
      live = false;
    };
  }, [name]);
  const shown =
    href === null ? (
      <span ref={ref} data-testid="my-trade-strategy-name" className={NAME}>
        {name}
      </span>
    ) : (
      <Link ref={ref as RefObject<HTMLAnchorElement | null>} to={href} data-testid="my-trade-strategy-name" className={cn(NAME, "text-gain hover:text-gain-bright")}>
        {name}
      </Link>
    );
  if (!cut) return shown;
  return (
    // The tip repeats the name, so it does not also describe the trigger.
    <Tooltip text={name} describes={false} placement={placement} className="flex min-w-0">
      {shown}
    </Tooltip>
  );
}

/** An amount in the page's masking: a price, or a dash for what the row does not have. */
function Price({ value }: { value: string | null }) {
  const { t } = useTranslation();
  if (value === null) return <span className="text-ink-3">{t("trades.noValue")}</span>;
  return <Masked>{tableFigureText(value) ?? t("trades.noValue")}</Masked>;
}

/** What a row says, the table's cells and the card's facts alike, so the two write each one the same way. */
function useFacts(line: TradeLine, placement: TipPlacement, asOf: string, mixed: boolean) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? "en";
  const open = line.kind === "open";
  const openedAt = openedAtOf(line);
  const side = sideOf(line);
  const currency = currencyOf(line);
  const rawPnl = open ? (line.position.unrealized_pnl ?? null) : line.trade.pnl;
  const pnl = rawPnl === null ? null : parseDecimal(rawPnl);
  const pnlText =
    pnl === null ? (
      <span className="text-ink-3">{t("trades.noValue")}</span>
    ) : (
      <Masked>{`${amountText(pnl, currency, locale, true)}${mixed ? ` ${currency}` : ""}`}</Masked>
    );

  return {
    opened: openedAt === null ? <span className="text-ink-3">{t("trades.noValue")}</span> : <Instant iso={openedAt} locale={locale} />,
    closed: open ? (
      <span className="flex items-center gap-2">
        <CloseSlot cause={null} placement={placement} />
        <Pill tone="gain" dot>
          {t("trades.open")}
        </Pill>
      </span>
    ) : (
      <span className="flex items-center gap-2">
        <CloseSlot cause={line.trade.close_cause} placement={placement} />
        <Instant iso={line.trade.closed_at} locale={locale} />
      </span>
    ),
    strategy: <StrategyName line={line} placement={placement} />,
    pair: (
      <span className="inline-flex items-center gap-1.5">
        {open ? (
          <PositionMark position={line.position} asOf={asOf} />
        ) : (
          <OriginDot origin={line.trade.rehearsal ? "rehearsal" : "live"} />
        )}
        {pairOf(line)}
      </span>
    ),
    side: side === null ? t("trades.noValue") : t(`positions.table.sideWord.${side}`),
    exchange: exchangeName(t, i18n, exchangeOf(line)),
    entry: <Price value={open ? line.position.entry_price : line.trade.entry_price} />,
    exit: open ? <span className="text-ink-3">{t("trades.noValue")}</span> : <Price value={line.trade.exit_price} />,
    pnl: open ? (
      // An open row's figure is the unrealized one, and its tip says so.
      <Tooltip text={t("trades.unrealized")} describes={false} placement={placement}>
        <span data-testid="my-trade-pnl-tip" className="cursor-help">
          {pnlText}
        </span>
      </Tooltip>
    ) : (
      pnlText
    ),
    pnlTone: pnl === null ? "" : toneClass(pnl),
  };
}

interface ListProps {
  lines: TradeLine[];
  asOf: string;
  /** The page holds more than one settlement currency: each amount names its own, and nothing is added (rule 7). */
  mixed: boolean;
  /** The currency of the heading when the page shares one. */
  currency: string | null;
  labelledBy: string;
}

function TradeRow({ line, placement, asOf, mixed }: { line: TradeLine; placement: TipPlacement; asOf: string; mixed: boolean }) {
  const facts = useFacts(line, placement, asOf, mixed);
  const cells: Array<[ReactNode, string]> = [
    [facts.opened, "font-mono tabular-nums text-ink-2"],
    [facts.closed, "font-mono tabular-nums text-ink-2"],
    [facts.strategy, "text-ink"],
    [facts.pair, "text-ink"],
    [facts.side, "text-ink"],
    [facts.exchange, "text-ink"],
    [facts.entry, FIGURE],
    [facts.exit, FIGURE],
    [facts.pnl, cn(FIGURE, facts.pnlTone)],
  ];
  return (
    <tr data-testid="my-trade-row" data-kind={line.kind}>
      {cells.map(([content, className], index) => (
        <td key={index} className={cn(TABLE_CELL, SIDES, className)}>
          {content}
        </td>
      ))}
    </tr>
  );
}

/** The prototype's ex4: the boxed table of the panel's other tables, at their 13 px. */
function TradesTable({ lines, asOf, mixed, currency, labelledBy }: ListProps) {
  const { t } = useTranslation();
  const heads: Array<[string, string?]> = [
    [t("trades.head.opened")],
    [t("trades.head.closed")],
    [t("trades.head.strategy")],
    [t("trades.head.pair")],
    [t("trades.head.side")],
    [t("trades.head.exchange")],
    [t("trades.head.entry"), "text-right"],
    [t("trades.head.exit"), "text-right"],
    [currency === null ? t("trades.head.pnl") : t("trades.head.pnlIn", { currency }), "text-right"],
  ];
  return (
    // No sideways scroll: this table turns into cards where it does not fit, and a box that scrolls one way clips
    // the other, which would cut a tip opened in it (the Users table's L50).
    <div className="rounded-lg border border-rule">
      <table aria-labelledby={labelledBy} className="w-full border-collapse">
        <thead>
          <tr>
            {heads.map(([label, className], index) => (
              <th
                key={index}
                scope="col"
                className={cn(
                  TABLE_HEAD,
                  SIDES,
                  index === 0 && "rounded-tl-[7px]",
                  index === heads.length - 1 && "rounded-tr-[7px]",
                  className,
                )}
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="text-left font-sans">
          {lines.map((line, index) => (
            <TradeRow key={line.key} line={line} placement={placementOf(index, lines.length)} asOf={asOf} mixed={mixed} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** One operation where the table does not fit: the strategy in the head, the facts labelled beneath. */
function TradeCard({ line, asOf, mixed, currency }: { line: TradeLine; asOf: string; mixed: boolean; currency: string | null }) {
  const { t } = useTranslation();
  const facts = useFacts(line, "above", asOf, mixed);
  const labelled: Array<[string, string, ReactNode, string?]> = [
    ["opened", t("trades.head.opened"), facts.opened],
    ["closed", t("trades.head.closed"), facts.closed],
    ["pair", t("trades.head.pair"), facts.pair],
    ["side", t("trades.head.side"), facts.side],
    ["exchange", t("trades.head.exchange"), facts.exchange],
    ["entry", t("trades.head.entry"), facts.entry],
    ["exit", t("trades.head.exit"), facts.exit],
    [
      "pnl",
      currency === null ? t("trades.head.pnl") : t("trades.head.pnlIn", { currency }),
      facts.pnl,
      cn("font-mono tabular-nums", facts.pnlTone),
    ],
  ];
  return (
    <article
      aria-label={strategyOf(line).name}
      data-testid="my-trade-row"
      data-kind={line.kind}
      className="flex min-w-0 flex-col gap-2.5 rounded-lg border border-rule bg-panel p-3.5"
    >
      <div className="min-w-0 break-words font-display text-base font-semibold text-ink">{facts.strategy}</div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-[13px] text-ink sm:grid-cols-4">
        {labelled.map(([key, label, value, className]) => (
          <div key={key} className="min-w-0">
            <dt className={LABEL}>{label}</dt>
            <dd className={className}>{value}</dd>
          </div>
        ))}
      </dl>
    </article>
  );
}

/** The table where its box holds it, the cards where it does not (L45), so no column runs past the card. */
export function TradesList(props: ListProps) {
  const wide = useIsWide(MD_QUERY);
  const { ref, fits } = useTableFits();
  if (wide && fits) {
    return (
      <div ref={ref}>
        <TradesTable {...props} />
      </div>
    );
  }
  return (
    <div ref={ref} className="flex flex-col gap-4">
      {props.lines.map((line) => (
        <TradeCard key={line.key} line={line} asOf={props.asOf} mixed={props.mixed} currency={props.currency} />
      ))}
    </div>
  );
}
