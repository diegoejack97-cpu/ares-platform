import { createContext, useContext } from "react";
import type { Session } from "@supabase/supabase-js";

export interface AuthState {
  session: Session;
  signOut: () => Promise<void>;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth deve estar dentro do AuthGate");
  return value;
}
