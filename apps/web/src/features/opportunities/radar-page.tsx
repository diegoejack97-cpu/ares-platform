import { ArrowRightIcon, FunnelIcon, PulseIcon } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { getOpportunities } from "./api";
import { money, signalLabels, slaLabel } from "./format";
import { RiskDistributionChart } from "./risk-distribution-chart";
import { ScoreBar } from "./score-bar";
import type { OpportunityListItem } from "./types";

const priorityLabels = ["Crítica", "Alta", "Média", "Baixa"];
const emptyItems: OpportunityListItem[] = [];

export function RadarPage() {
  const [state, setState] = useState("");
  const [minScore, setMinScore] = useState(0);
  const query = useQuery({
    queryKey: ["opportunities", state, minScore],
    queryFn: () =>
      getOpportunities({
        state: state || undefined,
        minScore: minScore || undefined,
      }),
    refetchInterval: 30_000,
  });
  const items = query.data?.items ?? emptyItems;
  const now = query.data ? new Date(query.data.freshness_at).getTime() : 0;
  const atRiskValue = useMemo(
    () => items.reduce((sum, item) => sum + item.deal_value, 0),
    [items],
  );

  return (
    <main className="workspace radar-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">ARES Connect · M2 Inteligência</span>
          <h1>Radar de receita recuperável</h1>
          <p>
            Prioridade operacional baseada em regras auditáveis. Score alto
            indica urgência; não afirma causalidade nem receita incremental.
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
        >
          <PulseIcon aria-hidden />{" "}
          {query.isFetching ? "Atualizando" : "Atualizar radar"}
        </Button>
      </header>

      <section className="radar-summary" aria-label="Resumo do Radar">
        <div>
          <span>Na fila</span>
          <strong>{items.length}</strong>
          <small>oportunidades abertas</small>
        </div>
        <div>
          <span>Valor em risco</span>
          <strong>{money(atRiskValue)}</strong>
          <small>valor dos negócios, não atribuição ARES</small>
        </div>
        <div>
          <span>SLA crítico</span>
          <strong>{items.filter((item) => item.priority === 0).length}</strong>
          <small>prioridade crítica</small>
        </div>
        <div>
          <span>Motor</span>
          <strong>m2.1</strong>
          <small>regras e score versionados</small>
        </div>
      </section>

      <section className="radar-layout">
        <div className="panel radar-table-panel">
          <div className="panel-heading radar-toolbar">
            <div>
              <h2>Fila priorizada</h2>
              <p>Ordenação fixa: prioridade → SLA → score</p>
            </div>
            <div className="radar-filters">
              <FunnelIcon aria-hidden />
              <label>
                Estado
                <select
                  value={state}
                  onChange={(event) => setState(event.target.value)}
                >
                  <option value="">Todos</option>
                  <option value="prioritized">Priorizada</option>
                  <option value="closed">Fechada</option>
                </select>
              </label>
              <label>
                Score mínimo
                <select
                  value={minScore}
                  onChange={(event) => setMinScore(Number(event.target.value))}
                >
                  <option value={0}>Todos</option>
                  <option value={0.5}>50</option>
                  <option value={0.7}>70</option>
                  <option value={0.8}>80</option>
                </select>
              </label>
            </div>
          </div>
          {query.isLoading ? (
            <div
              className="radar-loading"
              aria-label="Carregando oportunidades"
            >
              <i />
              <i />
              <i />
              <i />
            </div>
          ) : query.isError ? (
            <div className="empty-state">
              <strong>Não foi possível carregar o Radar</strong>
              <span>{query.error.message}</span>
              <Button onClick={() => void query.refetch()}>
                Tentar novamente
              </Button>
            </div>
          ) : items.length === 0 ? (
            <div className="empty-state">
              <strong>Nenhuma oportunidade neste recorte</strong>
              <span>
                Ajuste os filtros ou gere um evento de risco no FakeCRM.
              </span>
              <Button
                variant="outline"
                onClick={() => {
                  setState("");
                  setMinScore(0);
                }}
              >
                Limpar filtros
              </Button>
            </div>
          ) : (
            <div className="radar-table-wrap">
              <table className="radar-table">
                <thead>
                  <tr>
                    <th>Prioridade</th>
                    <th>Oportunidade</th>
                    <th>Sinal principal</th>
                    <th>Score</th>
                    <th>SLA</th>
                    <th>Valor</th>
                    <th>
                      <span className="sr-only">Abrir</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <span className={`priority-pill p${item.priority}`}>
                          {priorityLabels[item.priority]}
                        </span>
                      </td>
                      <td>
                        <strong>{item.title}</strong>
                        <small>
                          {item.external_stage ?? "Sem estágio"} ·{" "}
                          {item.signal_count} sinais
                        </small>
                      </td>
                      <td>
                        {signalLabels[item.primary_signal_type ?? ""] ??
                          item.primary_signal_type}
                      </td>
                      <td>
                        <ScoreBar
                          score={item.score}
                          breakdown={item.score_breakdown}
                        />
                      </td>
                      <td>
                        <span
                          className={
                            item.sla_at && new Date(item.sla_at).getTime() < now
                              ? "sla overdue"
                              : "sla"
                          }
                        >
                          {slaLabel(item.sla_at, now)}
                        </span>
                      </td>
                      <td className="tabular">
                        {money(item.deal_value, item.currency)}
                      </td>
                      <td>
                        <Link
                          className="row-link"
                          to={`/opportunities/${item.id}`}
                          aria-label={`Abrir ${item.title}`}
                        >
                          <ArrowRightIcon aria-hidden />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="provenance">
            Fonte: {query.data?.source ?? "ARES Core"} · Frescor:{" "}
            {query.data
              ? new Date(query.data.freshness_at).toLocaleTimeString("pt-BR")
              : "—"}
          </div>
        </div>
        <aside className="panel risk-panel">
          <div className="panel-heading">
            <div>
              <h2>Distribuição da fila</h2>
              <p>Quantidade por prioridade</p>
            </div>
          </div>
          <RiskDistributionChart items={items} />
          <ul>
            {priorityLabels.map((label, index) => (
              <li key={label}>
                <span className={`legend-dot p${index}`} />
                {label}
                <strong>
                  {items.filter((item) => item.priority === index).length}
                </strong>
              </li>
            ))}
          </ul>
        </aside>
      </section>
    </main>
  );
}
