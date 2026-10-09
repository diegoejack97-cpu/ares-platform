import { supabase } from "@/lib/supabase";
import type { MemoryConfig, DocumentUpload, Feedback } from "./contract";

export async function intelligenceRequest<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new Error("Sessão ausente.");
  const response = await fetch(
    `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1/intelligence/${path}`,
    {
      method,
      headers: {
        Authorization: `Bearer ${data.session.access_token}`,
        "Content-Type": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    },
  );
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(
      `Operação indisponível: ${detail?.error?.code ?? response.status}`,
    );
  }
  return response.json() as Promise<T>;
}

export type MemoryConfiguration = {
  configuration: Omit<MemoryConfig, "expected_version" | "reason"> & {
    version: number;
  };
  can_configure: boolean;
  limits: { memory_storage_bytes: number; embedding_daily_budget_brl: string };
  processing: string;
};
export type MemoryDocument = {
  id: string;
  title: string;
  source_label: string;
  current_version: number;
  status: string;
  expires_at: string;
  purposes: string[];
  allowed_roles: string[];
  owner_user_id: string | null;
  classification: "internal" | "restricted";
  error_code: string | null;
};
export const memoryConfiguration = () =>
  intelligenceRequest<MemoryConfiguration>("memory/configuration");
export const memorySaveConfiguration = (body: MemoryConfig) =>
  intelligenceRequest<MemoryConfiguration>("memory/configuration", "PUT", body);
export const memoryDocuments = () =>
  intelligenceRequest<{ items: MemoryDocument[] }>("memory/documents");
export const memoryUpload = (body: DocumentUpload) =>
  intelligenceRequest("memory/documents", "POST", body);
export const memoryRemove = (id: string, reason: string) =>
  intelligenceRequest(`memory/documents/${id}/delete`, "POST", { reason });
export type OutcomeView = {
  state: string;
  evaluation: null | {
    id: string;
    finished_at: string | null;
    error_code: string | null;
    explanation_json: null | {
      summary: string;
      limitations: string[];
      next_steps: string[];
    };
  };
  chain: null | {
    intervention_id: string;
    opportunity_id: string;
    state_before_ref: string;
    state_after_ref: string | null;
    concurrent_interventions: number;
    late_outcome: boolean;
    window: { start: string; end: string };
    outcome: null | { result_type: string; attribution_level: string };
  };
};
export const outcomeOpportunity = (id: string) =>
  intelligenceRequest<OutcomeView>(`outcomes/opportunity/${id}`);
export const outcomeStart = (id: string) =>
  intelligenceRequest(`outcomes/${id}`, "POST");
export const outcomeFeedback = (id: string, body: Feedback) =>
  intelligenceRequest(`outcomes/evaluation/${id}/feedback`, "POST", body);
export const outcomeEpisode = (id: string, reason: string) =>
  intelligenceRequest(`outcomes/evaluation/${id}/memory`, "POST", { reason });
export type OutcomeMetrics = {
  period_days: number;
  interventions: number;
  outcomes_observed: number;
  pending: number;
  source: string;
  coverage: string;
  adoption: { numerator: number; denominator: number; definition: string };
  rejection: { numerator: number; denominator: number; definition: string };
  execution_failure: {
    numerator: number;
    denominator: number;
    definition: string;
  };
  observed_state_change: {
    numerator: number;
    denominator: number;
    definition: string;
  };
  risk_resolution: {
    numerator: number;
    denominator: number;
    definition: string;
  };
  response_definition: string;
};
export const outcomeMetrics = (days: number) =>
  intelligenceRequest<OutcomeMetrics>(`outcomes/metrics?days=${days}`);
