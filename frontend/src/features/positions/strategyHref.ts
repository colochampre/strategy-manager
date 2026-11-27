/** The page this user can open: the detail is the author's, and a subscriber reaches the public page while it is listed. */
export function strategyHref(id: string | null, page: "AUTHORED" | "LISTED" | null): string | null {
  if (id === null) return null;
  if (page === "AUTHORED") return `/strategies/${id}`;
  return page === "LISTED" ? `/strategies/explore/${id}` : null;
}
