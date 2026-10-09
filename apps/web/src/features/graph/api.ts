import { supabase } from "@/lib/supabase";
import type { OpportunityGraph } from "@/features/agents/contract";

export class GraphError extends Error {
  status: number;
  correlationId?: string;
  constructor(status: number, correlationId?: string) {
    super(
      status === 404 || status === 403
        ? "Grafo indisponível neste acesso."
        : "Não foi possível consultar o grafo. Tente novamente.",
    );
    this.status = status;
    this.correlationId = correlationId;
  }
}
export async function getGraph(
  id: string,
  depth: number,
  signal?: AbortSignal,
): Promise<OpportunityGraph> {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new GraphError(401);
  const response = await fetch(
    `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1/opportunities/${encodeURIComponent(id)}/graph?depth=${depth}`,
    {
      signal,
      headers: { Authorization: `Bearer ${data.session.access_token}` },
    },
  );
  if (!response.ok) {
    const error = (await response.json().catch(() => null)) as {
      error?: { correlation_id?: string };
    } | null;
    throw new GraphError(response.status, error?.error?.correlation_id);
  }
  return response.json() as Promise<OpportunityGraph>;
}
