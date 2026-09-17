import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";

import { supabase } from "@/lib/supabase";

import { AuthContext } from "./auth-context";
import { LoginPage } from "./login-page";

export function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // getSession only reads local storage; a session revoked server-side
    // (password reset, admin sign-out) must fall back to the login page.
    const validate = async () => {
      const { data } = await supabase.auth.getSession();
      if (data.session) {
        const { error } = await supabase.auth.getUser();
        if (error) {
          await supabase.auth.signOut({ scope: "local" });
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
    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setLoading(false);
    });
    return () => {
      document.removeEventListener("visibilitychange", revalidate);
      data.subscription.unsubscribe();
    };
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
