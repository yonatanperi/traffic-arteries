import { createContext, useCallback, useEffect, useState } from "react";
import { loginUser, registerUser, refreshAccessToken, logoutUser, fetchMe } from "../api/accounts.js";
import { setAccessToken, registerRefreshHandlers } from "../api/httpClient.js";

export const AuthContext = createContext(null);

const REFRESH_TOKEN_KEY = "ta_refresh_token";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // {personal_id, first_name, last_name, role} | null
  const [initializing, setInitializing] = useState(true);

  const clearAuth = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
  }, []);

  const doRefresh = useCallback(async () => {
    const refresh = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (!refresh) throw new Error("no refresh token");
    const { access } = await refreshAccessToken(refresh);
    setAccessToken(access);
    return access;
  }, []);

  useEffect(() => {
    registerRefreshHandlers({ refresh: doRefresh, onFailure: clearAuth });
  }, [doRefresh, clearAuth]);

  // Silent refresh on app load — the access token never survives a reload
  // since it's kept in memory only.
  useEffect(() => {
    const refresh = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (!refresh) {
      setInitializing(false);
      return;
    }
    doRefresh()
      .then(() => fetchMe())
      .then(setUser)
      .catch(() => clearAuth())
      .finally(() => setInitializing(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function login(personalId, password) {
    const data = await loginUser(personalId, password); // {access, refresh, user}
    setAccessToken(data.access);
    localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh);
    setUser(data.user);
    return data.user;
  }

  async function register(payload) {
    await registerUser(payload);
    return login(payload.personal_id, payload.password);
  }

  async function logout() {
    const refresh = localStorage.getItem(REFRESH_TOKEN_KEY);
    try {
      if (refresh) await logoutUser(refresh);
    } finally {
      clearAuth();
    }
  }

  const role = user?.role ?? null;

  const value = {
    user,
    role,
    initializing,
    isAuthenticated: !!user,
    isEditorOrAdmin: role === "editor" || role === "admin",
    login,
    register,
    logout,
    refreshProfile: () => fetchMe().then(setUser),
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
