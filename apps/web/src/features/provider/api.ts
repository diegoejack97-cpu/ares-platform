import { createClient } from "@supabase/supabase-js";
import type {
  CreateTenant,
  BillingCommand,
  QuotaCommand,
  SetEntitlement,
  TenantConfiguration,
  TenantPage,
  TenantRecord,
} from "@/features/agents/contract";

export const providerAuth = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY,
  {
    auth: {
      storageKey: "ares-provider-session",
      storage: window.sessionStorage,
      detectSessionInUrl: false,
    },
  },
);

export class ProviderError extends Error {
  status: number;
  correlationId?: string;
  constructor(status: number, code: string, correlationId?: string) {
    super(
      status === 401 || status === 403
        ? "Esta conta não tem acesso de provedor. Use a conta dedicada."
        : code === "funnel_migration_required"
          ? "A troca de dono do funil exige migração assistida."
          : status === 409
            ? "A configuração mudou ou conflita com outro registro. Recarregue antes de salvar."
            : "Não foi possível concluir a operação. Tente novamente.",
    );
    this.status = status;
    this.correlationId = correlationId;
  }
}
async function request<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const { data } = await providerAuth.auth.getSession();
  if (!data.session) throw new ProviderError(401, "provider_session_required");
  const response = await fetch(
    `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1/admin${path}`,
    {
      method: body === undefined ? "GET" : "POST",
      signal,
      headers: {
        Authorization: `Bearer ${data.session.access_token}`,
        "Content-Type": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    },
  );
  if (!response.ok) {
    const result = await response.json().catch(() => null);
    throw new ProviderError(
      response.status,
      result?.error?.code ?? "operation_failed",
      result?.error?.correlation_id,
    );
  }
  return response.json();
}
export const listTenants = (cursor: string | null, signal?: AbortSignal) =>
  request<TenantPage>(
    `/tenants${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
    undefined,
    signal,
  );
export const tenantConfiguration = (id: string, signal?: AbortSignal) =>
  request<TenantConfiguration>(`/tenants/${id}`, undefined, signal);
export const createTenant = (command: CreateTenant) =>
  request<TenantRecord>("/tenants", command);
export const setEntitlement = (id: string, command: SetEntitlement) =>
  request<TenantRecord>(`/tenants/${id}/entitlements`, command);
export const setBilling = (id: string, command: BillingCommand) =>
  request<TenantRecord>(`/tenants/${id}/billing`, command);
export const setQuota = (id: string, command: QuotaCommand) =>
  request<TenantRecord>(`/tenants/${id}/quotas`, command);
