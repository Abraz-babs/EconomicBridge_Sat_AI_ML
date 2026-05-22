/**
 * EconomicBridge API client (open-access edition).
 *
 * No auth tokens — Step 5's JWT layer was removed. Tenant scoping is delivered
 * via the `X-Tenant-Id` header (set per-request by hooks/components that know
 * which tenant the user is viewing).
 *
 * Base URL: `NEXT_PUBLIC_API_BASE_URL` (defaults to http://localhost:8000/api/v1).
 *
 * The wrapper:
 *   - prepends the base URL
 *   - attaches `X-Tenant-Id` when supplied
 *   - parses the standard response envelope (CLAUDE.md §7) and returns the
 *     unwrapped `data` block on success
 *   - throws ApiException on HTTP error, with the parsed error envelope
 */

export const API_BASE_URL: string =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000/api/v1';

/**
 * Base URL for the satellite-ingestion microservice (separate process,
 * separate port). Used for live N2YO pass queries, manual FIRMS triggers,
 * and scheduler introspection. Unlike the API service it returns plain
 * JSON (no success/data envelope) — call via `ingestionFetch`, not
 * `apiFetch`.
 */
export const INGESTION_BASE_URL: string =
  process.env.NEXT_PUBLIC_INGESTION_BASE_URL ?? 'http://localhost:8001/api/v1';

/**
 * Base URL for the ML model-serving microservice (port 8002).
 * Hosts the conflict predictor + the ResNet-50 crop disease classifier.
 * Returns the SuccessResponse[T] envelope (same shape as the API
 * service), so `mlFetch` reuses the envelope-unwrapping logic.
 */
export const ML_BASE_URL: string =
  process.env.NEXT_PUBLIC_ML_BASE_URL ?? 'http://localhost:8002/api/v1';

/** Raw JSON fetcher for the ingestion service (no envelope unwrap). */
export async function ingestionFetch<T>(
  path: string,
  opts: { signal?: AbortSignal; method?: string; body?: unknown } = {},
): Promise<T> {
  const url = path.startsWith('http') ? path : `${INGESTION_BASE_URL}${path}`;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';

  let response: Response;
  try {
    response = await fetch(url, {
      method: opts.method ?? 'GET',
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch (err) {
    throw new ApiException(
      err instanceof Error ? err.message : 'Network error',
      0,
      null,
    );
  }

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = (body && (body.detail ?? body.error)) ?? detail;
    } catch {
      // non-JSON body — keep the status text we already have
    }
    throw new ApiException(`Ingestion: ${detail}`, response.status, null);
  }
  return (await response.json()) as T;
}

// ─── Envelope types (mirror schemas/envelope.py) ───────────────────────────

export interface ResponseMeta {
  tenant_id: string | null;
  trace_id: string;
  timestamp: string | null;
  pagination: { page: number; per_page: number; total: number } | null;
}

export interface ApiErrorDetail {
  code: string;
  message: string;
  trace_id: string;
}

export interface SuccessEnvelope<T> {
  success: true;
  data: T;
  meta: ResponseMeta;
  error: null;
}

export interface ErrorEnvelope {
  success: false;
  data: null;
  meta: ResponseMeta;
  error: ApiErrorDetail;
}

export class ApiException extends Error {
  status: number;
  body: ErrorEnvelope | null;
  /** Convenience: the structured error code, if the body had one. */
  code: string | null;

  constructor(message: string, status: number, body: ErrorEnvelope | null) {
    super(message);
    this.name = 'ApiException';
    this.status = status;
    this.body = body;
    this.code = body?.error?.code ?? null;
  }
}

// ─── Core fetch ────────────────────────────────────────────────────────────

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  /** Tenant slug for X-Tenant-Id. Omit for tenant-agnostic endpoints. */
  tenantId?: string | null;
  /** Aborter so React Query can cancel in-flight calls. */
  signal?: AbortSignal;
  /** Extra headers (rarely needed). */
  headers?: Record<string, string>;
}

/** Issue a request and return the parsed envelope. Throws ApiException on 4xx/5xx. */
export async function apiFetch<T>(
  path: string,
  opts: RequestOptions = {},
): Promise<SuccessEnvelope<T>> {
  const url = path.startsWith('http') ? path : `${API_BASE_URL}${path}`;
  const headers: Record<string, string> = { Accept: 'application/json', ...(opts.headers ?? {}) };
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  if (opts.tenantId) headers['X-Tenant-Id'] = opts.tenantId;

  let response: Response;
  try {
    response = await fetch(url, {
      method: opts.method ?? 'GET',
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch (err) {
    // Network-layer failure (CORS preflight, offline, DNS, …)
    throw new ApiException(
      err instanceof Error ? err.message : 'Network error',
      0,
      null,
    );
  }

  if (response.status === 204) {
    // No-content responses don't carry an envelope; synthesise an empty one.
    return {
      success: true,
      data: undefined as unknown as T,
      meta: {
        tenant_id: null,
        trace_id: response.headers.get('X-Trace-Id') ?? '',
        timestamp: null,
        pagination: null,
      },
      error: null,
    };
  }

  let parsed: unknown;
  try {
    parsed = await response.json();
  } catch {
    parsed = null;
  }

  if (!response.ok) {
    const body = (parsed as ErrorEnvelope | null) ?? null;
    const message =
      body?.error?.message ??
      `Request failed: ${response.status} ${response.statusText}`;
    throw new ApiException(message, response.status, body);
  }

  return parsed as SuccessEnvelope<T>;
}

/** Convenience: unwrap to `data` only. */
export async function apiGet<T>(
  path: string,
  opts: Omit<RequestOptions, 'method' | 'body'> = {},
): Promise<T> {
  const envelope = await apiFetch<T>(path, { ...opts, method: 'GET' });
  return envelope.data;
}

/**
 * Multipart POST for bulk-upload endpoints. Same envelope handling +
 * tenant header attach as `apiFetch`, but the body is FormData. Do NOT
 * set Content-Type manually — fetch derives it with the multipart
 * boundary automatically.
 */
export interface UploadOptions {
  tenantId?: string | null;
  signal?: AbortSignal;
}

export async function apiUpload<T>(
  path: string,
  formData: FormData,
  opts: UploadOptions = {},
): Promise<SuccessEnvelope<T>> {
  const url = path.startsWith('http') ? path : `${API_BASE_URL}${path}`;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (opts.tenantId) headers['X-Tenant-Id'] = opts.tenantId;

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers,
      body: formData,
      signal: opts.signal,
    });
  } catch (err) {
    throw new ApiException(
      err instanceof Error ? err.message : 'Network error',
      0,
      null,
    );
  }

  let parsed: unknown;
  try {
    parsed = await response.json();
  } catch {
    parsed = null;
  }

  if (!response.ok) {
    const body = (parsed as ErrorEnvelope | null) ?? null;
    // FastAPI emits 4xx as `{ detail: "..." }` for our HTTPException paths;
    // the success envelope only fires on 2xx. Cover both shapes.
    let message =
      body?.error?.message ??
      `Upload failed: ${response.status} ${response.statusText}`;
    if (parsed && typeof parsed === 'object') {
      const obj = parsed as { detail?: unknown };
      if (typeof obj.detail === 'string') message = obj.detail;
    }
    throw new ApiException(message, response.status, body);
  }

  return parsed as SuccessEnvelope<T>;
}

// ─── ML service helper ─────────────────────────────────────────────────────


/**
 * Issue a request against the ML microservice (port 8002) and return the
 * unwrapped `data` block. The ML service returns the same envelope shape
 * as the API service (CLAUDE.md §7) but lives on a separate origin, so
 * we just swap the base URL and reuse the envelope logic.
 *
 * Thrown ApiException carries the parsed FastAPI `detail` when present.
 */
export async function mlFetch<T>(
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const url = path.startsWith('http') ? path : `${ML_BASE_URL}${path}`;
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(opts.headers ?? {}),
  };
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  if (opts.tenantId) headers['X-Tenant-Id'] = opts.tenantId;

  let response: Response;
  try {
    response = await fetch(url, {
      method: opts.method ?? 'GET',
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch (err) {
    throw new ApiException(
      err instanceof Error ? err.message : 'Network error',
      0,
      null,
    );
  }

  let parsed: unknown;
  try {
    parsed = await response.json();
  } catch {
    parsed = null;
  }

  if (!response.ok) {
    // ML service uses FastAPI's default {detail: "..."} for 4xx/5xx;
    // some routes wrap as our error envelope. Handle both.
    let detail = `${response.status} ${response.statusText}`;
    if (parsed && typeof parsed === 'object') {
      const obj = parsed as { detail?: unknown; error?: { message?: string } };
      if (typeof obj.detail === 'string') detail = obj.detail;
      else if (obj.error?.message) detail = obj.error.message;
    }
    throw new ApiException(`ML: ${detail}`, response.status, null);
  }

  // Success envelope shape: { success, data, meta, error }
  const envelope = parsed as SuccessEnvelope<T> | null;
  if (!envelope || envelope.success !== true) {
    throw new ApiException(
      'ML service returned an unexpected response shape',
      response.status,
      null,
    );
  }
  return envelope.data;
}
