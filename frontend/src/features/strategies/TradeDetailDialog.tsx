import type { StrategyTrade } from "@/shared/api/types";

interface TradeDetailDialogProps {
  /** The strategy the operation belongs to; the fills request needs it. */
  strategyId: string;
  /** The row the dialog was opened from: every figure comes from it. */
  trade: StrategyTrade;
  /** The strategy's pool currency; every figure is in it (rule 7). */
  currency: string;
  locale: string;
  onClose: () => void;
}

/** STUB (task 9p.5.15, red): an empty dialog. Task 9p.5.16 builds the figures, the sentences and the fills table. */
export function TradeDetailDialog(_props: TradeDetailDialogProps) {
  return <dialog />;
}
