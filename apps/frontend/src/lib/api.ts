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
