interface OperationFillsTableProps {
  strategyId: string;
  allocationId: string;
  /** The operation's base currency, written in the Quantity heading. */
  baseCurrency: string;
  /** The operation's own rehearsal mark; a fill whose flag differs carries the Dry run tag. */
  operationRehearsal: boolean;
}

/** STUB (task 9p.5.17, red): renders nothing. Task 9p.5.18 builds the three states and the table. */
export function OperationFillsTable(_props: OperationFillsTableProps) {
  return null;
}
