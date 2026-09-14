import { supabase } from "@/lib/supabase";
import type { AgentSummary } from "./contract";

export class AgentReadError extends Error {
  status: number;
  correlationId?: string;
  constructor(status: number, correlationId?: string) {
    super(
      status === 401
        ? "Sua sessão expirou. Entre novamente."
        : status === 403
          ? "Esta consulta exige acesso de administrador, gestor ou auditor e licença ativa."
          : "Não foi possível consultar as execuções. Tente novamente.",
    );
    this.name = "AgentReadError";
    this.status = status;
    this.correlationId = correlationId;
  }
}

export async function getAgents(
  days: number,
  signal?: AbortSignal,
): Promise<AgentSummary> {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new AgentReadError(401);
  const response = await fetch(
    `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1/agents?days=${days}`,
    {
      signal,
      headers: { Authorization: `Bearer ${data.session.access_token}` },
    },
  );
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error?: { correlation_id?: string };
    } | null;
    throw new AgentReadError(response.status, body?.error?.correlation_id);
  }
  return response.json() as Promise<AgentSummary>;
}
