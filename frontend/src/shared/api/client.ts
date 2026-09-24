import { API_BASE_URL } from "@/shared/api/config";
import { useTokenStore } from "@/shared/auth/token-store";

interface RefusalLikeBody {
  outcome?: string;
  detail?: string;
}

/**
 * Every non-2xx response from the API is thrown as this typed error, so a
 * refusal (409 SUPERSEDED, 503 DRY_RUN_REFUSED, 422 REASON_REQUIRED, ...)
 * can never be read as success by a caller that only checks `.then`.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly outcome: string | undefined;
  readonly detail: string | undefined;

  constructor(status: number, body: RefusalLikeBody | undefined) {
    super(body?.detail ?? `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.outcome = body?.outcome;
    this.detail = body?.detail;
  }
}

async function parseErrorBody(response: Response): Promise<RefusalLikeBody | undefined> {
  try {
    return (await response.json()) as RefusalLikeBody;
  } catch {
    return undefined;
  }
}

/**
 * Sends the stored admin bearer token on every call and throws a typed
 * `ApiError` for any response that is not 2xx — never resolves a refusal as
 * success. Any 401 clears the token store, which makes `TokenGate` re-render
 * its paste-once form (design.md §12).
 */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = useTokenStore.getState().token;

  const headers = new Headers(init.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, { detail: "Network request failed" });
  }

  if (response.status === 401) {
    useTokenStore.getState().clearToken();
  }

  if (!response.ok) {
    const body = await parseErrorBody(response);
    throw new ApiError(response.status, body);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
