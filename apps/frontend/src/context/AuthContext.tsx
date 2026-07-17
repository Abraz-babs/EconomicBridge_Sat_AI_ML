'use client';

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { ApiException, apiFetch, setAccessToken, setRefreshHandler } from '@/lib/api';

/**
 * Real authentication for the control plane (super-admin + tenant accounts).
 *
 * The public dashboard stays anonymous — this context simply holds whoever (if
 * anyone) is signed in, and registers their access token with the api client so
 * authed calls (and the admin panel) work. Distinct from RoleContext, which is a
 * demo persona switch with no security meaning.
 *
 * Tokens live in localStorage so a refresh keeps you signed in; the access token
 * is short-lived (15 min) and transparently refreshed on 401 via the handler
 * registered with the api client.
 */

export interface AuthUser {
  id: string;
  email: string;
  role: string;
  org_id: string;
  full_name: string | null;
  permitted_tenants: string[];
  /** Registry slug of the user's OWN organisation — the subscription that
   *  module locks follow, regardless of which tenant is being viewed. */
  tenant_id?: string | null;
}

interface AuthContextValue {
  user: AuthUser | null;
  isSuperAdmin: boolean;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Activate an invited account (set first password) and sign in. */
  activate: (token: string, password: string) => Promise<void>;
}

const ACCESS_KEY = 'eb.auth.access';
const REFRESH_KEY = 'eb.auth.refresh';

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

interface TokenPair {
  access_token: string;
  refresh_token: string;
  user: AuthUser;
}

function store(access: string | null, refresh: string | null): void {
  if (typeof window === 'undefined') return;
  if (access) window.localStorage.setItem(ACCESS_KEY, access);
  else window.localStorage.removeItem(ACCESS_KEY);
  if (refresh) window.localStorage.setItem(REFRESH_KEY, refresh);
  else window.localStorage.removeItem(REFRESH_KEY);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  // Always start "loading" so the SSR render and the first client render agree
  // (reading localStorage during the initial render causes a hydration
  // mismatch — AuthControl would differ). The mount effect resolves it below.
  const [loading, setLoading] = useState<boolean>(true);
  // Refresh token kept in a ref so the (stable) refresh handler always reads the
  // latest value without being re-registered.
  const refreshTokenRef = useRef<string | null>(null);

  const clearSession = useCallback(() => {
    refreshTokenRef.current = null;
    setAccessToken(null);
    store(null, null);
    setUser(null);
  }, []);

  // Mint a new access token from the stored refresh token. Returns the token or
  // null. Registered with the api client for 401 retries.
  //
  // Session-clearing policy (2026-07-17 intermittent-logout fix): only clear
  // when the SERVER says the refresh token is bad (400/401/403). Network
  // blips, rolling-deploy 5xxs and timeouts are transient — punishing them
  // with a logout was why the operator kept getting signed out; on those we
  // keep the tokens and simply let the caller's request fail once (the next
  // action retries the refresh).
  const doRefresh = useCallback(async (): Promise<string | null> => {
    const refresh = refreshTokenRef.current;
    if (!refresh) return null;
    try {
      const env = await apiFetch<{ access_token: string }>('/auth/refresh', {
        method: 'POST', body: { refresh_token: refresh }, noAuth: true,
      });
      const token = env.data.access_token;
      setAccessToken(token);
      store(token, refresh);
      return token;
    } catch (e) {
      const status = e instanceof ApiException ? e.status : 0;
      if (status === 400 || status === 401 || status === 403) {
        clearSession(); // genuinely invalid/expired/revoked refresh token
      }
      return null;
    }
  }, [clearSession]);

  useEffect(() => {
    setRefreshHandler(doRefresh);
    return () => setRefreshHandler(null);
  }, [doRefresh]);

  // On mount (client only): restore a session from localStorage and re-hydrate
  // the user, then clear the loading flag. Runs after the first render so SSR +
  // hydration match. setState here is the intended post-mount resolution.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const access = window.localStorage.getItem(ACCESS_KEY);
    const refresh = window.localStorage.getItem(REFRESH_KEY);
    if (!access || !refresh) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLoading(false);
      return;
    }
    refreshTokenRef.current = refresh;
    setAccessToken(access);
    // Same transient-vs-invalid policy as doRefresh: a flaky connection at
    // page load must not destroy a valid session. One delayed retry covers
    // the blip; only an explicit auth rejection clears the tokens.
    let retryTimer: number | undefined;
    const hydrate = (attempt: number) => {
      apiFetch<AuthUser>('/auth/me')
        .then((env) => { setUser(env.data); setLoading(false); })
        .catch((e) => {
          const status = e instanceof ApiException ? e.status : 0;
          if (status === 401 || status === 403) {
            clearSession();
            setLoading(false);
          } else if (attempt === 0) {
            retryTimer = window.setTimeout(() => hydrate(1), 2500);
          } else {
            setLoading(false); // still offline — keep tokens, render signed-out UI
          }
        });
    };
    hydrate(0);
    return () => window.clearTimeout(retryTimer);
  }, [clearSession]);

  // Proactive refresh: renew the access token every ~12 minutes while the tab
  // is visible, so requests almost never land on the 401-expiry path at all
  // (the reactive refresh stays as the safety net). A failed background
  // renewal is harmless — doRefresh only clears on explicit rejection.
  useEffect(() => {
    if (!user) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') void doRefresh();
    }, 12 * 60 * 1000);
    return () => window.clearInterval(id);
  }, [user, doRefresh]);

  const adopt = useCallback((data: TokenPair) => {
    refreshTokenRef.current = data.refresh_token;
    setAccessToken(data.access_token);
    store(data.access_token, data.refresh_token);
    setUser(data.user);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const env = await apiFetch<TokenPair>('/auth/login', {
      method: 'POST', body: { email, password }, noAuth: true,
    });
    adopt(env.data);
  }, [adopt]);

  const activate = useCallback(async (token: string, password: string) => {
    const env = await apiFetch<TokenPair>('/auth/activate', {
      method: 'POST', body: { token, password }, noAuth: true,
    });
    adopt(env.data);
  }, [adopt]);

  const logout = useCallback(async () => {
    const refresh = refreshTokenRef.current;
    if (refresh) {
      try {
        await apiFetch('/auth/logout', {
          method: 'POST', body: { refresh_token: refresh }, noAuth: true,
        });
      } catch {
        // best-effort revoke; clear locally regardless
      }
    }
    clearSession();
  }, [clearSession]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isSuperAdmin: user?.role === 'super_admin',
      loading,
      login,
      logout,
      activate,
    }),
    [user, loading, login, logout, activate],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
