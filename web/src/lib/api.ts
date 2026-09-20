// The only place that knows fetch. Every screen goes through here.
export class ApiError extends Error { constructor(message: string, public status: number) { super(message); } }

export async function api<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError((body as { detail?: string }).detail || res.statusText, res.status);
  }
  return res.json() as Promise<T>;
}
export const send = <T = unknown>(path: string, body?: unknown, method = "POST") =>
  api<T>(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });

export const q = (params: Record<string, string | number | boolean | null | undefined>) =>
  Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "" && v !== false)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");

/** The list contract every paged endpoint answers. */
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }
export interface ListQuery { q?: string; sort?: string; dir?: "asc" | "desc"; page?: number; page_size?: number; [k: string]: string | number | undefined }
