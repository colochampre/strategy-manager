import type { Strategy } from "@/shared/api/types";

interface OpenMarksProps {
  strategy: Strategy;
}

/** Stub (RED step): draws nothing. */
export function OpenMarks({ strategy: _strategy }: OpenMarksProps) {
  return null;
}
