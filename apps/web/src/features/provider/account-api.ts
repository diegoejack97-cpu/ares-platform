import { supabase } from "@/lib/supabase";

export class AccountError extends Error {
  status: number;
  code: string;
  correlationId?: string;
  constructor(status: number, code: string, correlationId?: string) {
    super(
      status === 403 && code === "admin_required"
        ? "Somente administradores do tenant acessam esta área."
        : `Operação não concluída: ${code}. Correlação: ${correlationId ?? "não informada"}.`,
    );
    this.status = status;
    this.code = code;
    this.correlationId = correlationId;
  }
}

/** Tenant-scoped account routes (/api/v1/account/*) with the product session. */
export async function account<T>(path: string, body?: unknown): Promise<T> {
  const { data } = await supabase.auth.getSession();
  const response = await fetch(
    `${import.meta.env.VITE_API_URL ?? "http://localhost:8000"}/api/v1/account${path}`,
    {
      method: body ? "POST" : "GET",
      headers: {
        Authorization: `Bearer ${data.session?.access_token ?? ""}`,
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
    },
  );
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new AccountError(
      response.status,
      error?.detail?.code ?? String(response.status),
      error?.detail?.correlation_id,
    );
  }
  return response.json();
}

export type BillingStatus = {
  state: string;
  degraded: boolean;
  due_since?: string | null;
  grace_until?: string | null;
};

export type QuotaStatus = {
  configured: boolean;
  warning?: boolean;
  daily?: string;
  monthly?: string;
  reserved?: string;
  daily_reserved?: string;
  daily_available?: string;
  monthly_available?: string;
  ai_daily_budget_brl?: string;
  ai_monthly_budget_brl?: string;
};

export const brl = (value: string | number | undefined | null) =>
  Number(value ?? 0).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
