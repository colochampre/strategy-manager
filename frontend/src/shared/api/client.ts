import { API_BASE_URL, API_PREFIX } from "@/shared/api/config";
import { useTokenStore } from "@/shared/auth/token-store";

/**
 * FastAPI answers a refusal with `{"detail": "text"}`, or, for the structured
 * refusals, `{"detail": {"error": "CODE", "message": "text", ...extra}}`.
 * `detail` is `unknown` because a validation failure sends a list.
 */
interface RefusalLikeBody {
  outcome?: string;
  detail?: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Every non-2xx response from the API is thrown as this typed error, so a
 * refusal (409 SUPERSEDED, 503 DRY_RUN_REFUSED, 422 REASON_REQUIRED, ...)
 * can never be read as success by a caller that only checks `.then`.
 *
 * `detail` is always the human text: the string itself, or the `message` of a
 * structured detail, so `message` is never `[object Object]`. A structured
 * detail is also exposed whole as `fields` (the symbols of `UNKNOWN_PAIRS`,
 * say) and its `error` as `code`; `code` falls back to `outcome`.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly outcome: string | undefined;
  readonly detail: string | undefined;
  readonly code: string | undefined;
  readonly fields: Readonly<Record<string, unknown>> | undefined;

  constructor(status: number, body: RefusalLikeBody | undefined) {
    const rawDetail = body?.detail;
    const structured = isRecord(rawDetail) ? rawDetail : undefined;
    const message = structured?.message;
    const text = typeof rawDetail === "string" ? rawDetail : typeof message === "string" ? message : undefined;
    super(text ?? `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.outcome = body?.outcome;
    this.detail = text;
    this.fields = structured;
    this.code = typeof structured?.error === "string" ? structured.error : body?.outcome;
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
    response = await fetch(`${API_BASE_URL}${API_PREFIX}${path}`, { ...init, headers });
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
