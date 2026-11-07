import { ApiError } from "@/shared/api/client";
import type { Entry } from "@/shared/api/entry";

const KEY = "strategies.entry";
const DEAD_REASONS = new Set(["EXPIRED", "REVOKED", "SPENT"]);

/**
 * The text of a refusal that the link or the code earned (decision 41), or null when it is not one: a dead code
 * (410, by its reason), too many wrong codes (429), and a 404 when the reader came with a code or a link, which
 * then opened nothing. A 404 with neither is the caller's own text. The status and the reason decide, never the
 * server's wording.
 */
export function entryRefusal(error: unknown, entry: Entry): string | null {
  if (!(error instanceof ApiError)) return null;
  if (error.status === 429) return `${KEY}.tooMany`;
  if (error.status === 410) {
    const reason = error.fields?.reason;
    return typeof reason === "string" && DEAD_REASONS.has(reason) ? `${KEY}.dead.${reason}` : `${KEY}.dead.other`;
  }
  if (error.status === 404) {
    if (entry.code !== undefined) return `${KEY}.codeOpensNothing`;
    if (entry.link !== undefined) return `${KEY}.linkOpensNothing`;
  }
  return null;
}
