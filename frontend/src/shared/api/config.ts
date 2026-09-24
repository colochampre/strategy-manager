/**
 * A base URL is not a secret, so it is fine to read from a build-time env
 * variable (design.md §12 — the admin credential module deliberately never
 * takes this path). Empty string means "same origin", the default when the
 * frontend is served by the same host as the API.
 */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "";
