import { supabase } from "@/lib/supabase";
import type {
  ContextSnapshot,
  OpportunityDetail,
  OpportunityPage,
} from "./types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function request<T>(path: string): Promise<T> {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new Error("Sessão ARES ausente");
  const response = await fetch(`${API_URL}${path}`, {
    headers: { Authorization: `Bearer ${data.session.access_token}` },
  });
  if (!response.ok)
    throw new Error(`ARES API respondeu com status ${response.status}`);
  return response.json() as Promise<T>;
}

export function getOpportunities(filters: {
  state?: string;
  minScore?: number;
}): Promise<OpportunityPage> {
  const query = new URLSearchParams();
  if (filters.state) query.set("state", filters.state);
  if (filters.minScore !== undefined)
    query.set("min_score", String(filters.minScore));
  const suffix = query.size ? `?${query.toString()}` : "";
  return request(`/api/v1/opportunities${suffix}`);
}

export function getOpportunity(id: string): Promise<OpportunityDetail> {
  return request(`/api/v1/opportunities/${id}`);
}

export function getOpportunityContext(id: string): Promise<ContextSnapshot> {
  return request(`/api/v1/opportunities/${id}/context`);
}
