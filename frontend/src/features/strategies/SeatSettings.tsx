import { PoolShareEditor } from "@/features/strategies/PoolShareEditor";
import { SubscriptionLeverageEditor } from "@/features/strategies/SubscriptionLeverageEditor";
import { useLeverageDraft } from "@/features/strategies/useLeverageDraft";
import type { Strategy } from "@/shared/api/types";

interface SeatSettingsProps {
  /** Only what the editors read, so a subscriber's row, which holds no whole strategy, can use it. */
  strategy: Pick<Strategy, "id" | "subscription" | "archived_at">;
}

/**
 * The two settings of a seat, the share and the leverage, each with its own Save. The leverage being chosen
 * is one draft read by both: the share's amount line shows the notional at it before Save, as the margin
 * follows the share. A draft that is not a value yet reads as the saved leverage.
 */
export function SeatSettings({ strategy }: SeatSettingsProps) {
  const draft = useLeverageDraft(strategy.subscription?.leverage ?? 1);
  return (
    <>
      <PoolShareEditor strategy={strategy} leverage={draft.reading.valid ? draft.reading.value : undefined} />
      <SubscriptionLeverageEditor strategy={strategy} draft={draft} />
    </>
  );
}
