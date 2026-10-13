import { useId } from "react";
import { useTranslation } from "react-i18next";

import { PositionsTable } from "@/features/positions/PositionsTable";
import { useOpenPositions } from "@/shared/api/positions";
import type { OpenPool } from "@/shared/api/positions";

interface PoolOpenPositionsProps {
  pool: OpenPool;
}

/** A stub (task op.4.1): it draws every position it is given, whatever its pool. */
export function PoolOpenPositions({ pool: _pool }: PoolOpenPositionsProps) {
  const { t } = useTranslation();
  const headingId = useId();
  const open = useOpenPositions();

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2 id={headingId} className="font-display text-base font-semibold text-ink">
        {t("positions.table.title")}
      </h2>
      {open.data !== undefined && open.data.positions.length > 0 && (
        <PositionsTable
          variant="pool"
          positions={open.data.positions}
          asOf={open.data.as_of}
          currency={_pool.settlement_currency}
          labelledBy={headingId}
        />
      )}
    </section>
  );
}
