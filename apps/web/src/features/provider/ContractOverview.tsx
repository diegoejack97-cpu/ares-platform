import type { TenantConfiguration } from "@/features/agents/contract";
import { brl } from "./account-api";
import { currentPackage, packageLabels } from "./CompanyContractEditor";
import { useLiveClock } from "@/lib/live-clock";

const billingLabels: Record<string, string> = {
  active: "Adimplente",
  past_due: "Em atraso",
  degraded: "Acesso degradado",
};

export function ContractOverview({ data }: { data: TenantConfiguration }) {
  const now = useLiveClock();
  const selectedPackage = currentPackage(data);
  const activeModules = data.entitlements.filter(
    (item) => item.status === "active",
  );
  const connectEnabled =
    data.tenant.status === "active" &&
    activeModules.some(
      (item) =>
        item.module === "ares_connect" &&
        (!item.expires_at || Date.parse(item.expires_at) > now),
    );
  const expiry = activeModules
    .map((item) => item.expires_at)
    .filter((value): value is string => Boolean(value))
    .sort()[0];
  const occupied = data.usage.active_members + data.usage.pending_invitations;

  return (
    <section className="provider-overview" aria-label="Resumo do contrato">
      <div className="provider-overview-heading">
        <div>
          <h3>Plano e consumo</h3>
          <p>Limites contratados e uso medido da empresa selecionada.</p>
        </div>
        <span data-status={data.tenant.status}>
          {data.tenant.status === "active"
            ? "Empresa liberada"
            : "Empresa suspensa"}
        </span>
      </div>
      <dl className="provider-overview-grid">
        <div>
          <dt>Pacote</dt>
          <dd>
            {selectedPackage ? packageLabels[selectedPackage] : "Não definido"}
            <small>
              {activeModules.length
                ? activeModules.map((item) => item.module).join(" + ")
                : "Nenhum módulo ativo"}
            </small>
          </dd>
        </div>
        <div>
          <dt>Vencimento do pacote</dt>
          <dd>
            {expiry
              ? new Date(expiry).toLocaleString("pt-BR")
              : "Sem data final registrada"}
            {expiry && Date.parse(expiry) <= now ? (
              <small>Vencido</small>
            ) : null}
          </dd>
        </div>
        <div>
          <dt>Usuários e convites</dt>
          <dd>
            {occupied} / {data.quota?.seats_limit ?? "—"}
            <small>
              {data.usage.active_members} ativos ·{" "}
              {data.usage.pending_invitations} convites pendentes
            </small>
          </dd>
        </div>
        <div>
          <dt>Agentes ativos</dt>
          <dd>
            {data.quota
              ? connectEnabled && data.quota.agent_slots > 0
                ? 1
                : 0
              : "—"}{" "}
            / {data.quota?.agent_slots ?? "—"}
            <small>Follow-up e triagem · uma rotina disponível</small>
          </dd>
        </div>
        <div>
          <dt>Sentinelas ativas</dt>
          <dd>
            {data.quota
              ? connectEnabled && data.quota.sentinel_slots > 0
                ? 1
                : 0
              : "—"}{" "}
            / {data.quota?.sentinel_slots ?? "—"}
            <small>Alerta de SLA · uma regra disponível</small>
          </dd>
        </div>
        <div>
          <dt>Cobrança</dt>
          <dd>
            {data.billing
              ? (billingLabels[data.billing.state] ?? data.billing.state)
              : "Não configurada"}
            {data.billing?.grace_until ? (
              <small>
                Prazo de tolerância até{" "}
                {new Date(
                  `${data.billing.grace_until}T12:00:00`,
                ).toLocaleDateString("pt-BR")}
              </small>
            ) : null}
          </dd>
        </div>
        <div>
          <dt>IA · hoje</dt>
          <dd>
            {brl(data.usage.ai_spend_today_brl)} /{" "}
            {data.quota ? brl(data.quota.ai_daily_budget_brl) : "—"}
            <small>
              {data.usage.agent_runs_today} execuções registradas hoje
            </small>
          </dd>
        </div>
        <div>
          <dt>IA · mês</dt>
          <dd>
            {brl(data.usage.ai_spend_month_brl)} /{" "}
            {data.quota ? brl(data.quota.ai_monthly_budget_brl) : "—"}
            <small>
              {data.usage.agent_runs_month} execuções registradas no mês
            </small>
          </dd>
        </div>
      </dl>
      <p className="provider-overview-source">
        Fonte: contrato e contadores do tenant no banco. Os valores de IA
        refletem consumo registrado; a reserva em andamento é verificada antes
        da chamada ao modelo.
      </p>
    </section>
  );
}
