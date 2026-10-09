import { supabase } from "@/lib/supabase";
import type {
  SentinelSchedule,
  SentinelScheduleCommand,
  SentinelCatalog,
  SentinelRuleCommand,
  SentinelArchiveCommand,
} from "@/features/agents/contract";

export class SentinelConfigError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string) {
    super(
      code === "stale_sentinel_schedule"
        ? "A programação mudou em outra sessão. Atualize e revise antes de salvar."
        : code === "sentinel_capacity_unavailable" ||
            code === "sentinel_agent_capacity_unavailable"
          ? "O limite de sentinelas ativas do plano foi atingido. Pause outra regra ou ajuste o contrato."
          : code === "stale_sentinel_finding"
            ? "O achado mudou. Atualize a caixa antes de marcar a notificação."
            : code === "tenant_admin_required"
              ? "Somente o administrador da empresa pode alterar esta programação."
              : code === "sentinel_kind_immutable"
                ? "O tipo da regra não pode ser alterado. Crie uma nova regra."
                : "Não foi possível consultar ou salvar a programação da sentinela.",
    );
    this.status = status;
    this.code = code;
  }
}

async function scheduleRequest(
  command?: SentinelScheduleCommand,
): Promise<SentinelSchedule> {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new SentinelConfigError(401, "session_missing");
  const response = await fetch(
    `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1/sentinels/config`,
    {
      method: command ? "PUT" : "GET",
      headers: {
        Authorization: `Bearer ${data.session.access_token}`,
        "Content-Type": "application/json",
      },
      body: command ? JSON.stringify(command) : undefined,
    },
  );
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new SentinelConfigError(
      response.status,
      payload?.detail?.code ?? String(response.status),
    );
  }
  return response.json() as Promise<SentinelSchedule>;
}

export const getSentinelSchedule = () => scheduleRequest();
export const updateSentinelSchedule = (command: SentinelScheduleCommand) =>
  scheduleRequest(command);

async function ruleRequest<T>(
  path: string,
  method = "GET",
  body?: object,
): Promise<T> {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new SentinelConfigError(401, "session_missing");
  const response = await fetch(
    `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1/sentinels/rules${path}`,
    {
      method,
      headers: {
        Authorization: `Bearer ${data.session.access_token}`,
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
    },
  );
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new SentinelConfigError(
      response.status,
      payload?.detail?.code ?? String(response.status),
    );
  }
  return response.status === 204
    ? (undefined as T)
    : (response.json() as Promise<T>);
}

export const getSentinelCatalog = () => ruleRequest<SentinelCatalog>("");
export const createSentinelRule = (command: SentinelRuleCommand) =>
  ruleRequest<SentinelSchedule>("", "POST", command);
export const saveSentinelRule = (
  ruleId: string,
  command: SentinelRuleCommand,
) =>
  ruleRequest<SentinelSchedule>(
    `/${encodeURIComponent(ruleId)}`,
    "PUT",
    command,
  );
export const archiveSentinelRule = (
  ruleId: string,
  command: SentinelArchiveCommand,
) =>
  ruleRequest<void>(`/${encodeURIComponent(ruleId)}/archive`, "POST", command);

export type SentinelPreview = {
  matched_count: number;
  truncated: boolean;
  ai_called: boolean;
  items: { opportunity_id: string; title: string | null; due_at: string }[];
};
export const previewSentinelRule = (command: SentinelRuleCommand) =>
  ruleRequest<SentinelPreview>("/preview", "POST", command);

export type SentinelNotification = {
  id: string;
  opportunity_id: string;
  rule_title: string;
  title: string | null;
  revision: number;
  status: "open" | "updated" | "resolved" | "superseded";
  severity: string;
  summary: string | null;
  interpretation_status: string;
  interpretation_json: { summary: string; limitations: string[] } | null;
  detected_at: string;
  updated_at: string;
  is_read: boolean;
  is_archived: boolean;
};
export type NotificationPage = {
  items: SentinelNotification[];
  unread_count: number;
  total: number;
  next_offset: number | null;
  source: string;
};
async function notificationRequest<T>(path: string, body?: object): Promise<T> {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new SentinelConfigError(401, "session_missing");
  const response = await fetch(
    `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1/sentinels/notifications${path}`,
    {
      method: body ? "PUT" : "GET",
      headers: {
        Authorization: `Bearer ${data.session.access_token}`,
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
    },
  );
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new SentinelConfigError(
      response.status,
      payload?.detail?.code ?? String(response.status),
    );
  }
  return response.json() as Promise<T>;
}
export const getNotifications = (offset = 0, view = "all") =>
  notificationRequest<NotificationPage>(
    `?offset=${offset}&limit=10&view=${view}`,
  );
export const markNotification = (
  id: string,
  revision: number,
  action: "read" | "unread" | "archive" | "restore",
) =>
  notificationRequest(`/${encodeURIComponent(id)}`, {
    expected_revision: revision,
    action,
  });

export const getSentinelOptions = () =>
  ruleRequest<{
    members: { user_id: string; email: string | null; role: string }[];
    agent_slots: number;
    truncated: boolean;
  }>("/options");
