import type { KeyMarkSpec } from "@/shared/credentials/key-state";

export interface KeyMarkProps {
  mark: KeyMarkSpec;
  /** `tab` is plain text under an exchange's name; `tag` is the bordered tag of a card. */
  variant?: "tab" | "tag";
  /** The element drawn; a tag in a list is an `li`. */
  as?: "span" | "li" | "p";
  className?: string | undefined;
}

/** STUB (RED): renders nothing. */
export function KeyMark(_props: KeyMarkProps) {
  return null;
}
