import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  ArrowClockwiseIcon,
  CpuIcon,
  ShieldCheckIcon,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Freshness } from "@/components/live/freshness";
import { useAuth } from "@/features/auth/auth-context";
import { dateTime } from "@/features/opportunities/format";
import { AgentReadError, getAgents } from "./api";
import type { AgentMetrics } from "./contract";
import "./agents.css";

export function AgentsSkeleton() {
  return (
    <div
      className="agents-loading"
      role="status"
      aria-label="Carregando execuções dos agentes"
    >
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-44 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

function AgentRecord({ item }: { item: AgentMetrics }) {
  const fallback = item.generation_mode === "deterministic_fallback";
  return (
    <li className="agent-record">
      <div className="agent-identity">
        <span className="agent-symbol">
          <CpuIcon size={24} aria-hidden />
        </span>
        <div>
          <span className="eyebrow">
            {fallback ? "REGRA DETERMINÍSTICA" : "GERAÇÃO COM MODELO"}
          </span>
          <h2>
            {item.agent_name === "follow-up+triage"
              ? "Follow-up e Triagem"
              : item.agent_name}
          </h2>
          <p>
            Versão <code>{item.agent_version}</code>
            <span className="agent-divider" />
            {item.model_id ??
              (fallback
                ? "Sem modelo neste resultado"
                : "Modelo não informado")}
          </p>
        </div>
      </div>
      <dl className="agent-metrics">
        <div>
          <dt>Execuções</dt>
          <dd>{item.runs.toLocaleString("pt-BR")}</dd>
        </div>
        <div>
          <dt>Latência p95</dt>
          <dd>
            {item.latency_p95_ms === null
              ? "Não informada"
              : `${(item.latency_p95_ms / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 2 })} s`}
          </dd>
          <dd className="agent-metric-note">
            {item.latency_samples} amostras concluídas
          </dd>
        </div>
        <div>
          <dt>Custo em USD</dt>
          <dd>
            {item.cost_usd === null
              ? "Não informado"
              : item.cost_usd.toLocaleString("pt-BR", {
                  minimumFractionDigits: 6,
                  maximumFractionDigits: 9,
                })}
          </dd>
          <dd className="agent-metric-note">
            {item.cost_usd === null
              ? "Consumo ainda não medido"
              : `${item.cost_status === "partial" ? "Subtotal parcial" : "Custo calculado"} · ${item.cost_samples} execuções`}
          </dd>
        </div>
        <div>
          <dt>Tokens observados</dt>
          <dd>
            {item.input_tokens == null
              ? "Não informados"
              : `${item.input_tokens.toLocaleString("pt-BR")} entrada / ${(item.output_tokens ?? 0).toLocaleString("pt-BR")} saída`}
          </dd>
          <dd className="agent-metric-note">
            {item.usage_samples ?? 0} com medição · {item.not_called ?? 0} sem
            chamada
          </dd>
        </div>
      </dl>
      <dl className="agent-statuses" aria-label="Estados das execuções">
        <div>
          <dt>Com sucesso</dt>
          <dd>{item.succeeded}</dd>
        </div>
        <div>
          <dt>Em execução</dt>
          <dd>{item.running}</dd>
        </div>
        <div data-attention={item.degraded > 0}>
          <dt>Degradadas</dt>
          <dd>{item.degraded}</dd>
        </div>
        <div data-attention={item.failed > 0}>
          <dt>Falhas</dt>
          <dd>{item.failed}</dd>
        </div>
      </dl>
      <div className="agent-record-footer">
        <span>
          <ShieldCheckIcon aria-hidden />{" "}
          {item.autonomy === "read_only"
            ? "Somente leitura"
            : "Propõe recomendações"}
        </span>
        <span>Última execução: {dateTime(item.last_run_at)}</span>
      </div>
    </li>
  );
}

export function AgentsPage() {
  const { session } = useAuth();
  const [days, setDays] = useState(30);
  const query = useQuery({
    queryKey: [
      "agents",
      session.user.id,
      session.user.app_metadata.active_tenant_id,
      days,
    ],
    queryFn: ({ signal }) => getAgents(days, signal),
    refetchInterval: 30_000,
    retry: (count, error) =>
      !(error instanceof AgentReadError && [401, 403].includes(error.status)) &&
      count < 1,
  });
  const denied =
    query.error instanceof AgentReadError &&
    [401, 403].includes(query.error.status);
  const data = denied ? undefined : query.data;
  const correlation =
    query.error instanceof AgentReadError
      ? query.error.correlationId
      : undefined;

  return (
    <main className="workspace agents-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">ARES CONNECT / SUPERVISÃO</span>
          <h1>Agentes</h1>
          <p>
            Execuções e custo dos agentes. A programação das verificações de SLA
            fica em <Link to="/sentinels">Sentinelas</Link>.
          </p>
          <Freshness timestamp={data?.freshness_at} />
        </div>
        <div className="agents-controls">
          <label htmlFor="agent-window">
            Período
            <select
              id="agent-window"
              aria-label="Período"
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            >
              <option value={7}>Últimos 7 dias</option>
              <option value={30}>Últimos 30 dias</option>
              <option value={90}>Últimos 90 dias</option>
            </select>
          </label>
          <Button
            variant="outline"
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            <ArrowClockwiseIcon aria-hidden />
            {query.isFetching ? "Consultando…" : "Atualizar leitura"}
          </Button>
        </div>
      </header>
      {query.isError ? (
        <div className="agents-notice" role="alert">
          <strong>
            {denied ? "Acesso indisponível" : "Leitura indisponível"}
          </strong>
          <p>
            {query.error instanceof AgentReadError
              ? query.error.message
              : "Sem resposta do servidor. Verifique a conexão e tente novamente."}
          </p>
          {data ? (
            <p>Exibindo a última leitura bem-sucedida deste período.</p>
          ) : null}
          {correlation ? <code>Correlação: {correlation}</code> : null}
          <Button
            variant="outline"
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            Tentar novamente
          </Button>
        </div>
      ) : null}
      {query.isPending ? (
        <AgentsSkeleton />
      ) : data ? (
        <>
          <div className="agents-source">
            <span>Fonte: registros de execução ARES</span>
            <span>
              {dateTime(data.window.since)} até {dateTime(data.window.until)}
            </span>
          </div>
          {data.items.length ? (
            <ul
              className="agent-records"
              aria-label="Agentes e modos de execução"
            >
              {data.items.map((item) => (
                <AgentRecord
                  key={JSON.stringify([
                    item.agent_name,
                    item.agent_version,
                    item.generation_mode,
                    item.model_id,
                  ])}
                  item={item}
                />
              ))}
            </ul>
          ) : (
            <section className="empty-state">
              <CpuIcon size={32} aria-hidden />
              <h2>Nenhuma execução neste período</h2>
              <p>
                Amplie o período ou abra uma oportunidade no Radar para
                solicitar uma recomendação.
              </p>
              <Link to="/radar">Abrir Radar ARES</Link>
            </section>
          )}
          <details className="agents-explanation">
            <summary>Como interpretar esta leitura</summary>
            <dl>
              <div>
                <dt>Autonomia supervisionada</dt>
                <dd>
                  O agente propõe. A política autoriza a ação e o executor
                  registra o resultado. Ações que exigem aprovação seguem para
                  decisão humana.
                </dd>
              </div>
              <div>
                <dt>Execução degradada</dt>
                <dd>
                  Uma regra determinística produziu a recomendação de
                  contingência. Isso não comprova uma execução bem-sucedida do
                  modelo.
                </dd>
              </div>
              <div>
                <dt>Tempo e custo</dt>
                <dd>
                  O p95 cobre a duração registrada da execução inteira. Custo
                  ausente não significa custo zero, inclusive após falha do
                  modelo.
                </dd>
              </div>
              <div>
                <dt>Uma execução compartilhada</dt>
                <dd>
                  Follow-up e Triagem são registrados juntos. Seus números não
                  representam dois agentes executados separadamente.
                </dd>
              </div>
            </dl>
          </details>
        </>
      ) : null}
    </main>
  );
}
