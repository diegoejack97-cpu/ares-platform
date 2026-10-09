import { createClient } from "@supabase/supabase-js";
import type {
  CreateTenant,
  BillingCommand,
  QuotaCommand,
  SetEntitlement,
  SetInitialAdmin,
  SetPackage,
  SetTenantStatus,
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

const providerMessages: Record<string, string> = {
  funnel_migration_required:
    "A troca de dono do funil exige migração assistida.",
  company_activation_requires_plan:
    "Atribua um plano vigente antes de liberar a empresa.",
  company_activation_requires_quota:
    "Configure as licenças e cotas antes de liberar a empresa.",
  company_activation_requires_billing:
    "Defina a cobrança como adimplente antes de liberar a empresa.",
  company_activation_requires_admin:
    "Indique um administrador inicial antes de liberar a empresa.",
  initial_admin_already_assigned:
    "A empresa já tem usuários. A administração agora é feita em Licenças.",
  initial_admin_requires_seat:
    "Configure ao menos uma licença antes de indicar o administrador.",
  verified_initial_admin_required:
    "Use o e-mail de uma conta existente, verificada e sem vínculo com o provedor.",
};

export class ProviderError extends Error {
  status: number;
  correlationId?: string;
  constructor(status: number, code: string, correlationId?: string) {
    super(
      status === 401 || status === 403
        ? "Esta conta não tem acesso de provedor. Use a conta dedicada."
        : (providerMessages[code] ??
            (status === 409
              ? "A configuração mudou ou conflita com outro registro. Recarregue antes de salvar."
              : "Não foi possível concluir a operação. Tente novamente.")),
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
export const providerIdentity = () => request<{ role: "provider" }>("/me");
export const tenantConfiguration = (id: string, signal?: AbortSignal) =>
  request<TenantConfiguration>(`/tenants/${id}`, undefined, signal);
export const createTenant = (command: CreateTenant) =>
  request<TenantRecord>("/tenants", command);
export const setEntitlement = (id: string, command: SetEntitlement) =>
  request<TenantRecord>(`/tenants/${id}/entitlements`, command);
export const setPackage = (id: string, command: SetPackage) =>
  request<TenantRecord>(`/tenants/${id}/package`, command);
export const setTenantStatus = (id: string, command: SetTenantStatus) =>
  request<TenantRecord>(`/tenants/${id}/status`, command);
export const setInitialAdmin = (id: string, command: SetInitialAdmin) =>
  request<TenantRecord>(`/tenants/${id}/initial-admin`, command);
export const setBilling = (id: string, command: BillingCommand) =>
  request<TenantRecord>(`/tenants/${id}/billing`, command);
export const setQuota = (id: string, command: QuotaCommand) =>
  request<TenantRecord>(`/tenants/${id}/quotas`, command);
