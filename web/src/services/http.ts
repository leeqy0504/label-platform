export interface ApiErrorBody {
  code?: string;
  message?: string;
  detail?: string | { code?: string; message?: string; details?: unknown };
  details?: unknown;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body != null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(path, {
    ...init,
    headers,
    credentials: 'include',
  });
  if (response.ok) {
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }

  let body: ApiErrorBody = {};
  try {
    body = await response.json() as ApiErrorBody;
  } catch {
    // Non-JSON failures still become a typed API error.
  }
  const structured = typeof body.detail === 'object' ? body.detail : undefined;
  const message = structured?.message
    ?? body.message
    ?? (typeof body.detail === 'string' ? body.detail : undefined)
    ?? `请求失败 (${response.status})`;
  throw new ApiError(
    response.status,
    structured?.code ?? body.code ?? `http_${response.status}`,
    message,
    structured?.details ?? body.details,
  );
}
