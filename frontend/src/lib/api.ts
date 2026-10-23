let csrfToken: string | null = null;

async function csrf() {
  if (!csrfToken) {
    const response = await fetch("/api/v1/auth/csrf/", { credentials: "include" });
    csrfToken = (await response.json()).csrfToken;
  }
  return csrfToken;
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = options.method?.toUpperCase() || "GET";
  const headers = new Headers(options.headers);
  if (method !== "GET" && method !== "HEAD") headers.set("X-CSRFToken", (await csrf()) || "");
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let response = await fetch(`/api/v1${path}`, { ...options, headers, credentials: "include", cache: "no-store" });
  if (response.status === 403 && method !== "GET" && method !== "HEAD") {
    const failure = await response.clone().json().catch(() => ({}));
    if (typeof failure.detail === "string" && failure.detail.startsWith("CSRF Failed")) {
      csrfToken = null;
      headers.set("X-CSRFToken", (await csrf()) || "");
      response = await fetch(`/api/v1${path}`, { ...options, headers, credentials: "include", cache: "no-store" });
    }
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = data.detail || data.message || data.error?.message || Object.values(data)[0];
    throw new Error(typeof detail === "string" ? detail : Array.isArray(detail) && typeof detail[0] === "string" ? detail.join(" ") : `Request failed (${response.status})`);
  }
  if (path.startsWith("/auth/login/") || path.startsWith("/auth/register/") || path.startsWith("/auth/logout/")) csrfToken = null;
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
