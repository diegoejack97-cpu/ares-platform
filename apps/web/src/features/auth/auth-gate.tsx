import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { Session } from "@supabase/supabase-js";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

import { AuthContext } from "./auth-context";
import { LoginPage } from "./login-page";

function AuthenticatedSession({ children }: { children: ReactNode }) {
  // Each authenticated identity owns its complete query and mutation cache.
  // A late response can only reach the retired client, never the next tenant.
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: 1, refetchOnWindowFocus: false },
        },
      }),
  );

  useEffect(
    () => () => {
      void client.cancelQueries();
      client.clear();
    },
    [client],
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const authRevision = useRef(0);

  useEffect(() => {
    let active = true;
    // getSession only reads local storage; a session revoked server-side
    // (password reset, admin sign-out) must fall back to the login page.
    const validate = async () => {
      const revision = ++authRevision.current;
      const { data } = await supabase.auth.getSession();
      if (!active || revision !== authRevision.current) return;
      if (data.session) {
        const { error } = await supabase.auth.getUser();
        if (!active || revision !== authRevision.current) return;
        if (error) {
          await supabase.auth.signOut({ scope: "local" });
          if (active && revision === authRevision.current) {
            setSession(null);
            setLoading(false);
          }
          return;
        }
      }
      setSession(data.session);
      setLoading(false);
    };
    void validate();
    const revalidate = () => {
      if (document.visibilityState === "visible") void validate();
    };
    document.addEventListener("visibilitychange", revalidate);
    const { data } = supabase.auth.onAuthStateChange((event, nextSession) => {
      // The explicit validation above owns bootstrap. Supabase's initial
      // storage event must not bypass getUser or restore an outdated session.
      if (!active || event === "INITIAL_SESSION") return;
      authRevision.current += 1;
      setSession(nextSession);
      setLoading(false);
    });
    return () => {
      active = false;
      authRevision.current += 1;
      document.removeEventListener("visibilitychange", revalidate);
      data.subscription.unsubscribe();
    };
  }, []);

  const signOut = useCallback(async () => {
    // Detach all product state before waiting for network logout.
    authRevision.current += 1;
    setSession(null);
    setLoading(true);
    try {
      await supabase.auth.signOut();
    } finally {
      setLoading(false);
    }
  }, []);
  const value = useMemo(
    () => (session ? { session, signOut } : null),
    [session, signOut],
  );

  if (loading)
    return <div className="auth-loading">Validando sessão ARES…</div>;
  if (!session) return <LoginPage />;
  const identity = JSON.stringify([
    session.user.id,
    session.user.app_metadata?.active_tenant_id ?? null,
  ]);
  return (
    <AuthContext.Provider value={value}>
      <AuthenticatedSession key={identity}>{children}</AuthenticatedSession>
    </AuthContext.Provider>
  );
}
