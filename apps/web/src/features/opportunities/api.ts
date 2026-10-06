import { supabase } from "@/lib/supabase";
import type {
  ActionDraft,
  ApprovalPage,
  ContextSnapshot,
  OpportunityAnalytics,
  OpportunityDetail,
  OpportunityPage,
  SentinelPage,
} from "./types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new Error("Sessão ARES ausente");
  const response = await fetch(`${API_URL}${path}`, {
    method: options.method ?? "GET",
    headers: {
      Authorization: `Bearer ${data.session.access_token}`,
      "Content-Type": "application/json",
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!response.ok) {
    const detail = (await response.json().catch(() => null)) as {
      detail?: string | { code?: string; current_version?: number };
    } | null;
    const message =
      typeof detail?.detail === "string"
        ? detail.detail
        : (detail?.detail?.code ??
          `ARES API respondeu com status ${response.status}`);
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function getOpportunities(filters: {
  state?: string;
  minScore?: number;
  cursor?: string;
}): Promise<OpportunityPage> {
  const query = new URLSearchParams();
  if (filters.state) query.set("state", filters.state);
  if (filters.minScore !== undefined)
    query.set("min_score", String(filters.minScore));
  if (filters.cursor) query.set("cursor", filters.cursor);
  const suffix = query.size ? `?${query.toString()}` : "";
  return request(`/api/v1/opportunities${suffix}`);
}

export function getOpportunity(id: string): Promise<OpportunityDetail> {
  return request(`/api/v1/opportunities/${id}`);
}

export function getOpportunityContext(id: string): Promise<ContextSnapshot> {
  return request(`/api/v1/opportunities/${id}/context`);
}

export function generateRecommendation(
  id: string,
): Promise<{ run_id: string }> {
  return request(`/api/v1/opportunities/${id}/recommendations`, {
    method: "POST",
    body: { trigger: "manual" },
  });
}

export function decideRecommendation(
  id: string,
  command: {
    verdict: "approved" | "edited" | "rejected";
    expected_version: number;
    edited_payload?: ActionDraft;
    reason?: string;
  },
): Promise<{ decision_id: string; intent_id: string | null; status: string }> {
  return request(`/api/v1/recommendations/${id}/decide`, {
    method: "POST",
    body: command,
  });
}

export function getApprovals(): Promise<ApprovalPage> {
  return request("/api/v1/approvals");
}

export function getOpportunityAnalytics(): Promise<OpportunityAnalytics> {
  return request("/api/v1/opportunities/analytics");
}

export function getSentinels(): Promise<SentinelPage> {
  return request("/api/v1/sentinels");
}
