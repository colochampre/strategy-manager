/**
 * What the panel does when the API answers 401 (multi-user design AD11).
 *
 * The panel holds no credential: Cloudflare Access signs the person in before
 * the page loads and attaches its assertion to every request. A 401 therefore
 * means the Access session expired under an open page, and the fix is to load
 * the page again, which sends the person through Access's sign-in.
 *
 * At most once a minute. A 401 that survives a fresh sign-in is a server-side
 * problem (a wrong AUD tag, say), and reloading on every request would spin the
 * page forever. The time of the last reload is kept in `sessionStorage`; when it
 * cannot be stored, the page does not reload at all, for the same reason.
 */

export const REAUTH_STORAGE_KEY = "sm.reauth_at";
export const REAUTH_WINDOW_MS = 60_000;

/** The two effects, behind an object so tests can replace them. */
export const page = {
  reload: (): void => window.location.reload(),
  now: (): number => Date.now(),
};

/** Reloads the page unless it already did within the last minute; says whether it did. */
export function reauthenticate(): boolean {
  const now = page.now();
  try {
    const last = Number(window.sessionStorage.getItem(REAUTH_STORAGE_KEY));
    if (Number.isFinite(last) && last > 0 && now - last < REAUTH_WINDOW_MS) {
      return false;
    }
    window.sessionStorage.setItem(REAUTH_STORAGE_KEY, String(now));
  } catch {
    return false;
  }
  page.reload();
  return true;
}
