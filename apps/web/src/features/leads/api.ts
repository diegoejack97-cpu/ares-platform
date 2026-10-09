import { supabase } from "@/lib/supabase";
import type {
  LeadInput,
  LeadResolve,
  LeadRecord,
  LeadPage,
  LeadCandidate,
} from "@/features/agents/contract";
async function request<T>(path: string, body?: unknown): Promise<T> {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new Error("Sessão expirada.");
  const response = await fetch(
    `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1/leads${path}`,
    {
      method: body ? "POST" : "GET",
      headers: {
        Authorization: `Bearer ${data.session.access_token}`,
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
    },
  );
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(
      `Não foi possível concluir: ${error?.detail?.code ?? "serviço indisponível"}. Recarregue e tente novamente. Correlação: ${error?.detail?.correlation_id ?? "não informada"}`,
    );
  }
  return response.json();
}
export const listLeads = (cursor: string | null) =>
  request<LeadPage>(cursor ? `?cursor=${cursor}` : "");
export const createIntake = (body: LeadInput) => request<LeadRecord>("", body);
export const candidates = (id: string) =>
  request<LeadCandidate[]>(`/${id}/candidates`);
export const resolveLead = (id: string, body: LeadResolve) =>
  request<LeadRecord>(`/${id}/resolve`, body);
