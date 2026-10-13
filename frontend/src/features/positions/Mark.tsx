export type MarkOrigin = "rehearsal" | "live" | "mixed" | "unknown";

export type MarkProps =
  | { kind: "position"; origin: MarkOrigin; pair: string; side: "LONG" | "SHORT" | null }
  | { kind: "order"; origin: MarkOrigin; pair: string }
  | { kind: "venue" };

/** Stub (RED step): draws every kind the same way, with no variant. */
export function Mark(props: MarkProps) {
  return <span className="border">{props.kind === "venue" ? "" : props.pair}</span>;
}
