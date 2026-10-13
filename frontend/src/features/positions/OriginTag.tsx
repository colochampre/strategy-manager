import type { MarkOrigin } from "@/features/positions/Mark";

interface OriginTagProps {
  origin: MarkOrigin;
}

/** Stub (RED step): the origin without its word or its token. */
export function OriginTag({ origin: _origin }: OriginTagProps) {
  return <span />;
}
