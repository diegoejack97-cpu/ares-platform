import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";

import { supabase } from "@/lib/supabase";

import { AuthContext } from "./auth-context";
import { LoginPage } from "./login-page";

export function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });
    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setLoading(false);
    });
    return () => data.subscription.unsubscribe();
  }, []);

  const value = useMemo(
    () =>
      session
        ? {
            session,
            signOut: async () => {
              await supabase.auth.signOut();
            },
          }
        : null,
    [session],
  );

  if (loading)
    return <div className="auth-loading">Validando sessão ARES…</div>;
  if (!value) return <LoginPage />;
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
