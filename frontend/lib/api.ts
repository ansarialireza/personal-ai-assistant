export type ApiError = Error & { status?: number };

const baseUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const accessKey = "pai_access";
const refreshKey = "pai_refresh";

export function saveTokens(access: string, refresh: string) {
  localStorage.setItem(accessKey, access);
  localStorage.setItem(refreshKey, refresh);
}

export function clearTokens() {
  localStorage.removeItem(accessKey);
  localStorage.removeItem(refreshKey);
}

export function hasTokens() {
  return Boolean(localStorage.getItem(accessKey));
}

async function refreshAccess() {
  const refresh = localStorage.getItem(refreshKey);
  if (!refresh) return false;
  const response = await fetch(`${baseUrl}/api/v1/auth/token/refresh/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });
  if (!response.ok) return false;
  const tokens = await response.json();
  saveTokens(tokens.access, tokens.refresh || refresh);
  return true;
}

export async function api<T>(path: string, options: RequestInit = {}, retried = false): Promise<T> {
  const headers = new Headers(options.headers);
  const access = localStorage.getItem(accessKey);
  if (access) headers.set("Authorization", `Bearer ${access}`);
  const isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (options.body && !isForm && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`${baseUrl}/api/v1${path}`, { ...options, headers });
  if (response.status === 401 && !retried && await refreshAccess()) return api<T>(path, options, true);
  if (response.status === 401) clearTokens();
  if (!response.ok) {
    let detail = `Request failed (${response.status}).`;
    try {
      const payload = await response.json();
      const value = payload.detail || payload.error || payload;
      detail = typeof value === "string" ? value : JSON.stringify(value);
    } catch {
      detail = `Request failed (${response.status}).`;
    }
    const error = new Error(detail) as ApiError;
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const json = (value: unknown): string => JSON.stringify(value);
