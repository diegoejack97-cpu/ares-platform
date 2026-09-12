import { supabase } from "@/lib/supabase";
import type {
  IntegrationJob,
  IntegrationMapping,
  PipelineSnapshot,
  StageCommand,
  StageResult,
} from "./types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class PipelineError extends Error {
  status: number;
  code: string;
  correlationId?: string;

  constructor(
    message: string,
    status: number,
    code: string,
    correlationId?: string,
  ) {
    super(message);
    this.name = "PipelineError";
    this.status = status;
    this.code = code;
    this.correlationId = correlationId;
  }
}

async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const { data } = await supabase.auth.getSession();
  if (!data.session)
    throw new PipelineError(
      "Sessão ausente. Entre novamente.",
      401,
      "session_missing",
    );
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${data.session.access_token}`,
        "Content-Type": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new PipelineError(
      "Sem resposta do servidor. O resultado da operação ainda não foi confirmado.",
      0,
      "network_uncertain",
    );
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      error?: { code?: string; message?: string; correlation_id?: string };
      detail?:
        string | { code?: string; message?: string; correlation_id?: string };
    } | null;
    const detail =
      payload?.error ??
      (typeof payload?.detail === "object" ? payload.detail : undefined);
    throw new PipelineError(
      detail?.message ??
        (typeof payload?.detail === "string"
          ? payload.detail
          : `Solicitação não concluída (HTTP ${response.status}${detail?.code ? ` · ${detail.code}` : ""}).`),
      response.status,
      detail?.code ?? "request_failed",
      detail?.correlation_id,
    );
  }
  return response.json() as Promise<T>;
}

export const getPipeline = (cursor?: string) =>
  request<PipelineSnapshot>(
    `/api/v1/pipeline${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
export const getIntegrationMapping = () =>
  request<IntegrationMapping>("/api/v1/integrations/mapping");
export const saveIntegrationMapping = (body: {
  expected_version: number;
  fields: IntegrationMapping["mapping"]["fields"];
  stages: IntegrationMapping["mapping"]["stages"];
}) => request<unknown>("/api/v1/integrations/mapping", "PUT", body);
export const startIntegrationSync = (body: {
  mode: "incremental" | "reconcile" | "historical";
  since?: string;
  until?: string;
}) => request<unknown>("/api/v1/integrations/sync", "POST", body);
export const getIntegrationJobs = () =>
  request<{ items: IntegrationJob[] }>("/api/v1/integrations/jobs");
export const retryIntegrationJob = (id: string) =>
  request<unknown>(
    `/api/v1/integrations/jobs/${encodeURIComponent(id)}/retry`,
    "POST",
  );
export const movePipelineDeal = (id: string, command: StageCommand) =>
  request<StageResult>(
    `/api/v1/pipeline/deals/${encodeURIComponent(id)}/stage`,
    "POST",
    command,
  );
