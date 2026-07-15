import axios from "axios";

// The access token lives only in memory (never localStorage) — it's held
// here, outside React state, because the axios interceptors below run
// outside the render cycle. AuthContext calls setAccessToken() on every
// change (login, silent refresh, logout).
let accessToken = null;
export function setAccessToken(token) {
  accessToken = token;
}

// In dev VITE_API_URL is unset, so baseURL stays "/api" and the Vite dev
// server proxies it to Django (same origin, no CORS). In production it's set
// to the Render backend origin (e.g. https://traffic-arteries.onrender.com),
// making cross-origin calls to that host's /api.
const API_BASE = import.meta.env.VITE_API_URL ?? "";
export const http = axios.create({
  baseURL: `${API_BASE}/api`,
  headers: { "Content-Type": "application/json" },
});

http.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

// Wired up once by AuthProvider on mount.
let onRefresh = null; // async () => newAccessToken; throws if refresh invalid
let onRefreshFailure = null; // () => void — clears auth state
export function registerRefreshHandlers({ refresh, onFailure }) {
  onRefresh = refresh;
  onRefreshFailure = onFailure;
}

let refreshPromise = null; // dedupes concurrent 401s into one refresh call

http.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config;
    const status = error.response && error.response.status;
    const isAuthRoute =
      original?.url?.includes("/accounts/login") || original?.url?.includes("/accounts/token/refresh");

    if (status === 401 && !original._retry && !isAuthRoute && onRefresh) {
      original._retry = true;
      try {
        if (!refreshPromise) {
          refreshPromise = onRefresh().finally(() => {
            refreshPromise = null;
          });
        }
        const newToken = await refreshPromise;
        original.headers.Authorization = `Bearer ${newToken}`;
        return http(original);
      } catch (refreshError) {
        if (onRefreshFailure) onRefreshFailure();
        return Promise.reject(refreshError);
      }
    }
    return Promise.reject(error);
  }
);

// DRF returns either {"detail": "..."} (our own views' convention) or, for
// serializer validation errors (register/login), a field-keyed dict like
// {"password2": ["הסיסמאות אינן תואמות."]} or {"non_field_errors": [...]}.
// Surface the first message we can find so callers get something useful
// instead of the generic fallback.
function extractErrorMessage(data) {
  if (!data || typeof data !== "object") return null;
  if (typeof data.detail === "string") return data.detail;
  for (const value of Object.values(data)) {
    if (Array.isArray(value) && typeof value[0] === "string") return value[0];
    if (typeof value === "string") return value;
  }
  return null;
}

// Preserves the existing convention where callers do
// `.catch((e) => setError(e.message))`.
export function unwrap(promise) {
  return promise
    .then((res) => res.data)
    .catch((err) => {
      const message = extractErrorMessage(err.response?.data) || "אירעה שגיאה בשרת.";
      throw new Error(message);
    });
}
