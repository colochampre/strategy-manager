import { useOpenPositions } from "@/shared/api/positions";

interface OpenStateLineProps {
  exchange: string;
  visibleStrategyIds: ReadonlySet<string> | null;
}

/** Stub (RED step): draws `Open: 0` whenever it has no data, the failure the real component must never have. */
export function OpenStateLine({ exchange: _exchange, visibleStrategyIds: _visible }: OpenStateLineProps) {
  const open = useOpenPositions();
  return <p>Open: {open.data?.positions.length ?? 0}</p>;
}
