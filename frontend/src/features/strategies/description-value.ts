/** The most characters a description may hold once the server has trimmed it. */
export const DESCRIPTION_MAX = 2000;

/** What the server reads of a description: blank, or a length in characters and whether it is over the limit. */
export type DescriptionReading = { blank: true } | { blank: false; tooLong: boolean; length: number };

/**
 * Trims only the four characters the server trims (space, tab, CR, LF). `String.prototype.trim` would also strip a
 * non-breaking space and other Unicode spaces, which the server keeps.
 */
export function trimLikeTheServer(text: string): string {
  return text.replace(/^[ \t\r\n]+/, "").replace(/[ \t\r\n]+$/, "");
}

/**
 * Reads a description as the server will: trimmed at both ends, a blank one is nothing, and the length is
 * counted in characters (code points), not UTF-16 units. The control-character rule is not mirrored here;
 * the server's refusal covers it.
 */
export function readDescription(text: string): DescriptionReading {
  const trimmed = trimLikeTheServer(text);
  if (trimmed === "") return { blank: true };
  const length = [...trimmed].length;
  return { blank: false, tooLong: length > DESCRIPTION_MAX, length };
}
