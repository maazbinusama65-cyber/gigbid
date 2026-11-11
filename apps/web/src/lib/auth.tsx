import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from "react";
import { api, ApiError, getToken, setToken, UNAUTHORIZED_EVENT, unwrap } from "./client";
import type { UserOut } from "./types";

interface AuthValue {
  user: UserOut | null;
  loading: boolean;
  signIn: (token: string) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const hasToken = getToken() !== null;
  const me = useQuery({
    queryKey: ["me"],
    enabled: hasToken,
    retry: false,
    queryFn: async () => {
      try {
        return await unwrap(api.GET("/api/auth/me"));
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) setToken(null);
        throw e;
      }
    },
  });

  const clear = useCallback(() => {
    setToken(null);
    qc.clear();
  }, [qc]);

  useEffect(() => {
    const onUnauthorized = () => {
      clear();
      window.location.assign("/sign-in");
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [clear]);

  const value = useMemo<AuthValue>(
    () => ({
      user: getToken() ? (me.data ?? null) : null,
      loading: hasToken && me.isPending,
      signIn: async (token: string) => {
        setToken(token);
        await qc.invalidateQueries({ queryKey: ["me"] });
        await qc.fetchQuery({ queryKey: ["me"], queryFn: () => unwrap(api.GET("/api/auth/me")) });
      },
      signOut: async () => {
        try {
          await api.POST("/api/auth/logout");
        } finally {
          clear();
        }
      },
      refresh: async () => {
        await qc.invalidateQueries({ queryKey: ["me"] });
      },
    }),
    [me.data, me.isPending, hasToken, qc, clear],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
