/**
 * A base URL is not a secret, so it is fine to read from a build-time env
 * variable (design.md §12 — the admin credential module deliberately never
 * takes this path). Empty string means "same origin", the default when the
 * frontend is served by the same host as the API.
 */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "";

/**
 * Every admin route is mounted under this prefix (design.md §13, spec:
 * admin-api). `apiFetch` is the one place that adds it, so every caller keeps
 * its existing relative path unchanged.
 */
export const API_PREFIX = "/api";
