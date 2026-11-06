export type LinkSegment = { kind: "text"; text: string } | { kind: "link"; text: string };

// An http or https URL that does not continue a word, up to whitespace, angle brackets, quotes or a backtick.
const CANDIDATE = /(?<![A-Za-z0-9+.-])https?:\/\/[^\s<>"`]+/gi;
const SCHEME = /^https?:\/\//i;
const TRAILING_MARKS = new Set([".", ",", ";", ":", "!", "?"]);

function count(text: string, char: string): number {
  return text.split(char).length - 1;
}

/** How much of a candidate is the URL: trailing sentence marks and an unbalanced ")" belong to the prose. */
function urlLength(candidate: string): number {
  let end = candidate.length;
  while (end > 0) {
    const last = candidate[end - 1] as string;
    const kept = candidate.slice(0, end);
    if (TRAILING_MARKS.has(last) || (last === ")" && count(kept, ")") > count(kept, "("))) end -= 1;
    else break;
  }
  return end;
}

/**
 * Splits plain text into text and link segments. Only http and https URLs become links; every other scheme, and
 * anything without a scheme, stays text. The segments joined back give the input exactly.
 */
export function linkify(input: string): LinkSegment[] {
  const segments: LinkSegment[] = [];
  let cursor = 0;
  const push = (kind: LinkSegment["kind"], text: string) => {
    if (text === "") return;
    const previous = segments[segments.length - 1];
    if (kind === "text" && previous?.kind === "text") previous.text += text;
    else segments.push({ kind, text });
  };
  for (const match of input.matchAll(CANDIDATE)) {
    const start = match.index;
    const url = match[0].slice(0, urlLength(match[0]));
    if (url.replace(SCHEME, "") === "") continue;
    push("text", input.slice(cursor, start));
    push("link", url);
    cursor = start + url.length;
  }
  push("text", input.slice(cursor));
  return segments;
}
