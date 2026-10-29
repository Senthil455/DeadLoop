import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  api,
  ApiError,
  apiGet,
  clearStoredToken,
  getStoredToken,
  storeToken,
  verifyAdminToken,
} from "./api";
import type { Health } from "./types";

export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const requestId = useRef(0);

  useEffect(() => {
    if (!path) {
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }
    const current = ++requestId.current;
    setLoading(true);
    setError(null);
    // The path itself is the dependency; callers build deterministic query strings.
    apiGet<T>(path)
      .then((value) => {
        if (current === requestId.current) {
          setData(value);
          setLoading(false);
        }
      })
      .catch((reason: unknown) => {
        if (current === requestId.current) {
          setError(reason instanceof Error ? reason.message : "Unable to load data.");
          setLoading(false);
        }
      });
  }, [path, nonce]);

  return {
    data,
    loading,
    error,
    reload: useCallback(() => setNonce((value) => value + 1), []),
    setData,
  };
}

interface AuthContextValue {
  token: string;
  ready: boolean;
  login: (token: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(() => getStoredToken());
  const [ready, setReady] = useState(true);

  useEffect(() => {
    const onUnauthorized = () => {
      clearStoredToken();
      setToken("");
    };
    window.addEventListener("deadloop:unauthorized", onUnauthorized);
    return () => window.removeEventListener("deadloop:unauthorized", onUnauthorized);
  }, []);

  const login = useCallback(async (candidate: string) => {
    setReady(false);
    try {
      await verifyAdminToken(candidate.trim());
      storeToken(candidate.trim());
      setToken(candidate.trim());
    } finally {
      setReady(true);
    }
  }, []);

  const logout = useCallback(() => {
    clearStoredToken();
    setToken("");
  }, []);

  const value = useMemo(
    () => ({ token, ready, login, logout }),
    [token, ready, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider.");
  return value;
}

interface SystemContextValue {
  health: Health | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
  demoMode: boolean;
}

const SystemContext = createContext<SystemContextValue | null>(null);

export function SystemProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const token = useAuth().token;

  useEffect(() => {
    let active = true;
    setLoading(true);
    api
      .health()
      .then((value) => {
        if (active) {
          setHealth(value);
          setError(null);
        }
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Health check failed.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [nonce, token]);

  useEffect(() => {
    if (!token) return;
    const timer = window.setInterval(() => setNonce((value) => value + 1), 30_000);
    return () => window.clearInterval(timer);
  }, [token]);

  const value = useMemo<SystemContextValue>(
    () => ({
      health,
      loading,
      error,
      refresh: () => setNonce((value) => value + 1),
      demoMode: Boolean(health?.demo_mode),
    }),
    [health, loading, error],
  );
  return <SystemContext.Provider value={value}>{children}</SystemContext.Provider>;
}

export function useSystem(): SystemContextValue {
  const value = useContext(SystemContext);
  if (!value) throw new Error("useSystem must be used inside SystemProvider.");
  return value;
}

export function useDocumentTitle(title: string): void {
  useEffect(() => {
    document.title = title ? `${title} · DEADLOOP` : "DEADLOOP · Agent reliability monitor";
  }, [title]);
}

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
