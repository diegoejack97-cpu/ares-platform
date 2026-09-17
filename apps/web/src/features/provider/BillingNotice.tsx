import { useQuery } from "@tanstack/react-query";
import { NoticeBar } from "@/components/console";
import {
  account,
  brl,
  type BillingStatus,
  type QuotaStatus,
} from "./account-api";

const date = (value?: string | null) =>
  value ? new Date(`${value}T00:00:00`).toLocaleDateString("pt-BR") : null;

export function BillingNotice() {
  const query = useQuery({
    queryKey: ["account-billing"],
    queryFn: () => account<BillingStatus>("/billing"),
    refetchInterval: 60000,
    retry: false,
  });
  if (query.error)
    return (
      <NoticeBar tone="neutral" title="Cobrança">
        Estado de cobrança indisponível no momento. As ações continuam sendo
        verificadas pelo servidor.
      </NoticeBar>
    );
  if (!query.data || !["past_due", "degraded"].includes(query.data.state))
    return null;
  if (query.data.degraded)
    return (
      <NoticeBar tone="critical" title="Prazo de pagamento encerrado.">
        Escrita e IA estão suspensas; leitura e histórico continuam disponíveis.
      </NoticeBar>
    );
  return (
    <NoticeBar tone="warning" title="Pagamento pendente.">
      Regularize até {date(query.data.grace_until) ?? "o prazo contratual"}. O
      produto permanece disponível até lá.
    </NoticeBar>
  );
}

export function QuotaNotice() {
  const query = useQuery({
    queryKey: ["account-quota"],
    queryFn: () => account<QuotaStatus>("/quota"),
    refetchInterval: 60000,
    retry: false,
  });
  if (query.error)
    return (
      <NoticeBar tone="neutral" title="Cota de IA">
        Consumo indisponível no momento. O servidor verifica o limite antes de
        cada execução.
      </NoticeBar>
    );
  if (!query.data) return null;
  if (!query.data.configured)
    return (
      <NoticeBar tone="warning" title="Cota de IA não configurada.">
        Novas execuções de IA ficam bloqueadas até o provedor definir o
        contrato.
      </NoticeBar>
    );
  if (Number(query.data.ai_daily_budget_brl) <= 0)
    return (
      <NoticeBar tone="critical" title="Cota de IA zerada pelo provedor.">
        Execuções de IA estão bloqueadas; leitura e histórico continuam
        disponíveis.
      </NoticeBar>
    );
  if (!query.data.warning) return null;
  return (
    <NoticeBar tone="warning" title="Cota de IA perto do limite.">
      Consumo e reservas atingiram pelo menos 80% do contrato:{" "}
      {brl(query.data.daily)} hoje e {brl(query.data.monthly)} no mês, para
      limites de {brl(query.data.ai_daily_budget_brl)}/dia e{" "}
      {brl(query.data.ai_monthly_budget_brl)}/mês.
    </NoticeBar>
  );
}
