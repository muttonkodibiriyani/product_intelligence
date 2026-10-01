'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ApiError, createApiClient, type ApiClient } from '@/lib/api/client';
import { loadWebConfig, startAuth, type AuthHandle, type Session } from '@/lib/auth/firebase';

export type AuthState =
  | { kind: 'loading' }
  | { kind: 'unavailable' }
  | { kind: 'signed_out' }
  | { kind: 'signed_in'; session: Session };

interface AuthContextValue {
  state: AuthState;
  auth: AuthHandle | null;
  api: ApiClient | null;
}

const AuthContext = createContext<AuthContextValue>({ state: { kind: 'loading' }, auth: null, api: null });

export const useAuth = () => useContext(AuthContext);

/** Retries only a dropped connection. auth_unavailable is already retried inside the client. */
export function shouldRetry(failureCount: number, e: unknown): boolean {
  if (!(e instanceof ApiError)) return false;
  return e.code === 'network' && failureCount < 2;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ kind: 'loading' });
  const [auth, setAuth] = useState<AuthHandle | null>(null);
  const queryClient = useMemo(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: shouldRetry, staleTime: 60_000, refetchOnWindowFocus: false } },
      }),
    [],
  );

  useEffect(() => {
    let stop: (() => void) | undefined;
    let cancelled = false;
    void loadWebConfig().then((config) => {
      if (cancelled) return;
      if (!config) return setState({ kind: 'unavailable' });
      const handle = startAuth(config);
      setAuth(handle);
      stop = handle.watch((s) => {
        if (!s) queryClient.clear();
        setState(s ? { kind: 'signed_in', session: s } : { kind: 'signed_out' });
      });
    });
    return () => {
      cancelled = true;
      stop?.();
    };
  }, [queryClient]);

  const api = useMemo(
    () =>
      auth &&
      createApiClient({
        getToken: auth.getToken,
        // A fresh token was still refused: sign in again.
        onUnauthenticated: () => void auth.signOut(),
        // New data was published: everything cached describes the old dataset.
        onGeneration: () => void queryClient.invalidateQueries(),
      }),
    [auth, queryClient],
  );

  const value = useMemo(() => ({ state, auth, api }), [state, auth, api]);
  return (
    <AuthContext.Provider value={value}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </AuthContext.Provider>
  );
}
