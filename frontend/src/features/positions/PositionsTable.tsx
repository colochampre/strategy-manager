import type { OpenPosition } from "@/shared/api/positions";

interface PositionsTableProps {
  positions: OpenPosition[];
  /** The answer's `as_of`. */
  asOf: string;
  /** The pool's settlement currency, written in the Fees and Margin headings. */
  currency: string;
  /** The id of the heading that names the table. */
  labelledBy: string;
  variant: "strategy";
}

/** STUB (op.3.1): every cell is written from a default. The real table is written in op.3.7. */
export function PositionsTable({ positions, labelledBy }: PositionsTableProps) {
  return (
    <table aria-labelledby={labelledBy}>
      <tbody>
        {positions.map((position) => (
          <tr key={position.allocation_id}>
            <td />
            <td />
            <td />
            <td />
            <td />
            <td />
            <td />
            <td>1x</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
