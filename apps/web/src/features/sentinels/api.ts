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
        : code === "sentinel_capacity_unavailable"
          ? "O limite de sentinelas ativas do plano foi atingido. Pause outra regra ou ajuste o contrato."
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
