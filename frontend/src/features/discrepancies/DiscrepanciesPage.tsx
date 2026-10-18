import { useId } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { BookedList } from "@/features/discrepancies/BookedList";
import { DiscrepancyItem } from "@/features/discrepancies/DiscrepancyItem";
import type { DiscrepancyVariant } from "@/features/discrepancies/DiscrepancyItem";
import { ReadLine, ReadState } from "@/features/discrepancies/ReadLine";
import { groupByExchange } from "@/features/discrepancies/groupByExchange";
import { useConfirmedDiscrepancies } from "@/shared/api/discrepancies";
import type { ConfirmedDiscrepancy, ConfirmedReading } from "@/shared/api/discrepancies";
import { useHashScroll } from "@/shared/lib/useHashScroll";
import { ReportSection } from "@/shared/ui/ReportSection";

interface SectionProps {
  headingId: string;
  title: string;
  note?: string;
  children: ReactNode;
}

function Section({ headingId, title, note, children }: SectionProps) {
  return (
    <section aria-labelledby={headingId} className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h2 id={headingId} className="font-display text-lg font-semibold text-ink">
          {title}
        </h2>
        {note !== undefined && <p className="text-xs text-ink-3">{note}</p>}
      </div>
      {children}
    </section>
  );
}

interface ItemsProps {
  items: readonly ConfirmedDiscrepancy[];
  variant: DiscrepancyVariant;
  readAt: string;
}

/** One list of discrepancy items under an exchange heading each, whatever exchange tab was last selected. */
function Items({ items, variant, readAt }: ItemsProps) {
  return (
    <>
      {groupByExchange(items).map((group) => (
        <ExchangeGroup key={group.exchange} exchange={group.exchange}>
          <div className="flex flex-col gap-3">
            {group.items.map((item) => (
              <DiscrepancyItem key={item.discrepancy_id} item={item} variant={variant} readAt={readAt} />
            ))}
          </div>
        </ExchangeGroup>
      ))}
    </>
  );
}

interface ExchangeGroupProps {
  exchange: string;
  children: ReactNode;
}

function ExchangeGroup({ exchange, children }: ExchangeGroupProps) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex min-w-0 flex-col gap-2">
      <h3 id={headingId} className="font-mono text-sm font-medium text-ink-2">
        {exchange}
      </h3>
      {children}
    </section>
  );
}

interface ListsProps {
  reading: ConfirmedReading;
}

/** The three sections, in order: "Needs you", "Being booked" (only when not empty), "Booked automatically". */
function Lists({ reading }: ListsProps) {
  const { t } = useTranslation();
  const needsId = useId();
  const beingId = useId();
  const bookedId = useId();
  const { needs_owner: needsOwner, being_booked: beingBooked, booked } = reading;

  return (
    <>
      <Section headingId={needsId} title={t("discrepancies.section.needsYou")}>
        {needsOwner.length > 0 ? (
          <Items items={needsOwner} variant="needsYou" readAt={reading.read_at} />
        ) : (
          // The second sentence of the all-clear is false while a booking is under way.
          <p className="text-sm text-ink-2">
            {beingBooked.length > 0 ? t("discrepancies.empty.needsYouWhileBooking") : t("discrepancies.empty.needsYou")}
          </p>
        )}
      </Section>
      {beingBooked.length > 0 && (
        <Section headingId={beingId} title={t("discrepancies.section.beingBooked")} note={t("discrepancies.note.beingBooked")}>
          <Items items={beingBooked} variant="beingBooked" readAt={reading.read_at} />
        </Section>
      )}
      <ReportSection>
        <Section headingId={bookedId} title={t("discrepancies.section.booked")} note={t("discrepancies.note.booked")}>
          {booked.length > 0 ? (
            <BookedList items={booked} labelledBy={bookedId} />
          ) : (
            <p className="text-sm text-ink-3">{t("discrepancies.empty.booked")}</p>
          )}
        </Section>
      </ReportSection>
    </>
  );
}

/**
 * The confirmed discrepancies of the whole system (owner decision 66): the title, its sentence, the read line,
 * "Needs you", "Being booked" and "Booked automatically". It reads one query, the badge's own, and no exchange
 * scope. It never reads as an all-clear without having looked: a first read that has not answered or has failed
 * draws no list (K row 8), and `dry_run` draws its sentence and no list at all, whatever the route holds (note
 * N3, K row 14).
 */
export function DiscrepanciesPage() {
  const { t } = useTranslation();
  const confirmed = useConfirmedDiscrepancies();
  const reading = confirmed.data;
  // The items exist only once a read has answered, and not at all in dry run.
  useHashScroll(reading !== undefined && !reading.dry_run);

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="font-display text-2xl font-bold text-ink">{t("discrepancies.title")}</h1>
        {reading !== undefined && <p className="max-w-3xl text-sm text-ink-2">{t("discrepancies.lede")}</p>}
      </div>
      {reading === undefined ? (
        <ReadState status={confirmed.status} errorUpdateCount={confirmed.errorUpdateCount} />
      ) : (
        <>
          <ReadLine readAt={reading.read_at} stale={confirmed.status === "error"} />
          {reading.dry_run ? (
            <p role="status" className="rounded-md border border-rule-strong bg-panel p-4 text-sm text-ink-2">
              {t("discrepancies.read.dryRun")}
            </p>
          ) : (
            <Lists reading={reading} />
          )}
        </>
      )}
    </div>
  );
}
