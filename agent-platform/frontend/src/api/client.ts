const API_BASE = "/api/admin";

interface TokenPair {
  access_token: string;
  refresh_token: string;
}

function getTokens(): TokenPair | null {
  const raw = localStorage.getItem("tokens");
  return raw ? JSON.parse(raw) : null;
}

function setTokens(tokens: TokenPair) {
  localStorage.setItem("tokens", JSON.stringify(tokens));
}

function clearTokens() {
  localStorage.removeItem("tokens");
}

async function refreshAccessToken(): Promise<string | null> {
  const tokens = getTokens();
  if (!tokens?.refresh_token) return null;

  const res = await fetch(`${API_BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: tokens.refresh_token }),
  });

  if (!res.ok) {
    clearTokens();
    return null;
  }

  const data: TokenPair = await res.json();
  setTokens(data);
  return data.access_token;
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const tokens = getTokens();

  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  if (tokens?.access_token) {
    headers["Authorization"] = `Bearer ${tokens.access_token}`;
  }

  let res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  // Token expired → try refresh
  if (res.status === 401 && tokens?.refresh_token) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      headers["Authorization"] = `Bearer ${newToken}`;
      res = await fetch(`${API_BASE}${path}`, { ...options, headers });
    }
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    throw new ApiError(res.status, detail || "Error desconocido");
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

export async function download(path: string, fallbackName: string): Promise<void> {
  let tokens = getTokens();
  const request = (accessToken?: string) => fetch(`${API_BASE}${path}`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });
  let res = await request(tokens?.access_token);
  if (res.status === 401 && tokens?.refresh_token) {
    const accessToken = await refreshAccessToken();
    tokens = getTokens();
    if (accessToken) res = await request(tokens?.access_token);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    throw new ApiError(res.status, detail || "No se pudo descargar el archivo");
  }
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename\*?=(?:UTF-8''|\")?([^";]+)/i);
  const filename = match ? decodeURIComponent(match[1].replace(/"$/, "")) : fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export { getTokens, setTokens, clearTokens };
export type { TokenPair };
