import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  ArrowSquareOutIcon,
  ArrowsClockwiseIcon,
  DownloadSimpleIcon,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  NoticeBar,
  StatTile,
  StatusBadge,
  shortId,
} from "@/components/console";
import type { ImpactIntervention } from "@/features/agents/contract";
import { impactSummary, impactPage, downloadImpact } from "./api";
import {
  attributionLabels,
  compact,
  interventionStatus,
  money,
  resultLabels,
  when,
} from "./format";
import "./impact.css";
import { OutcomeMetricsPanel } from "@/features/agents/outcome-panel";

function Result({ row }: { row: ImpactIntervention }) {
  if (!row.result_type)
    return <span className="cell-muted">Ainda não observado</span>;
  return (
    <div className="cell-stack">
      <strong>{resultLabels[row.result_type] ?? row.result_type}</strong>
      {row.attribution_level ? (
        <small>
          {attributionLabels[row.attribution_level] ?? row.attribution_level}
        </small>
      ) : null}
    </div>
  );
}

export function ImpactPage() {
  const [days, setDays] = useState(30),
    [cursor, setCursor] = useState<string | null>(null);
  const summary = useQuery({
    queryKey: ["impact", days],
    queryFn: ({ signal }) => impactSummary(days, signal),
    retry: false,
  });
  const page = useQuery({
    queryKey: ["impact-interventions", days, cursor],
    queryFn: ({ signal }) => impactPage(days, cursor, signal),
    retry: false,
  });
  const download = useMutation({
    mutationFn: (format: "csv" | "pdf") => downloadImpact(days, format),
  });
  const data = summary.isError ? undefined : summary.data;
  const synthetic = data?.amounts.some((a) => a.synthetic_observations > 0);
  const recovered = data?.amounts.reduce((sum, a) => sum + a.recovered, 0) ?? 0;
  const observations =
    data?.amounts.reduce((sum, a) => sum + a.observations, 0) ?? 0;
  return (
    <main className="workspace console-page impact-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">RESULTADOS E EVIDÊNCIAS</span>
          <h1>Impacto ARES</h1>
          <p>
            Venda observada, influência e incrementalidade com definições
            explícitas.
          </p>
        </div>
        <div className="toolbar">
          <div className="field">
            <label htmlFor="impact-days">Período</label>
            <select
              id="impact-days"
              value={days}
              onChange={(e) => {
                setDays(Number(e.target.value));
                setCursor(null);
              }}
            >
              <option value={7}>7 dias</option>
              <option value={30}>30 dias</option>
              <option value={90}>90 dias</option>
            </select>
          </div>
          <Button
            variant="outline"
            disabled={summary.isFetching || page.isFetching}
            onClick={() => {
              void summary.refetch();
              void page.refetch();
            }}
          >
            <ArrowsClockwiseIcon aria-hidden /> Atualizar relatório
          </Button>
          {(["csv", "pdf"] as const).map((format) => (
            <Button
              key={format}
              variant={format === "csv" ? "outline" : "default"}
              disabled={!data || download.isPending}
              onClick={() => download.mutate(format)}
            >
              <DownloadSimpleIcon aria-hidden /> Exportar {format.toUpperCase()}
            </Button>
          ))}
        </div>
      </header>
      <OutcomeMetricsPanel days={days} />
      {download.isPending ? (
        <NoticeBar tone="info">Preparando exportação auditada…</NoticeBar>
      ) : null}
      {download.error ? (
        <NoticeBar
          tone="critical"
          role="alert"
          title="Exportação não concluída."
        >
          {download.error.message}
        </NoticeBar>
      ) : null}
      {summary.error ? (
        <NoticeBar tone="critical" role="alert" title="Relatório indisponível.">
          {summary.error.message}
        </NoticeBar>
      ) : null}
      {synthetic ? (
        <NoticeBar tone="warning" title="Dados sintéticos.">
          Este relatório contém dados sintéticos de demonstração. Os valores não
          representam resultados comerciais reais.
        </NoticeBar>
      ) : null}
      {summary.isPending ? (
        <div className="console-stack" aria-busy="true">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : null}
      {data ? (
        <div className="console-stack impact-report">
          <div className="stat-grid">
            <StatTile
              label="Em risco"
              value={compact(data.counts.at_risk)}
              note="Oportunidades ainda abertas na data da consulta"
            />
            <StatTile
              label="Trabalhadas"
              value={compact(data.counts.worked)}
              note={`Com intervenção nos últimos ${data.window.days} dias`}
            />
            <StatTile
              label="Recuperadas"
              value={compact(recovered)}
              note={`Último outcome de ${compact(observations)} ${observations === 1 ? "oportunidade observada" : "oportunidades observadas"}`}
            />
            <StatTile
              label="Custo de IA"
              value={
                data.ai_cost.cost_usd === null
                  ? "Não informado"
                  : `USD ${Number(data.ai_cost.cost_usd).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`
              }
              muted={data.ai_cost.cost_usd === null}
              note={`${compact(data.ai_cost.measured_runs)} de ${compact(data.ai_cost.runs)} execuções com custo medido`}
            />
          </div>
          <section className="panel" aria-labelledby="impact-amounts">
            <div className="panel-heading">
              <div>
                <h2 id="impact-amounts">Valores por moeda</h2>
                <p>Último resultado observado por oportunidade no período.</p>
              </div>
            </div>
            {!data.amounts.length ? (
              <p className="data-empty">
                Nenhum resultado observado no período. Registre o outcome com
                evidência no fluxo da oportunidade; ausência não representa
                receita zero.
              </p>
            ) : (
              <div
                className="data-table"
                role="region"
                aria-label="Valores por moeda, tabela rolável"
                tabIndex={0}
              >
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Moeda</th>
                      <th scope="col" className="is-numeric">
                        Vendido
                      </th>
                      <th scope="col" className="is-numeric">
                        Influenciado
                      </th>
                      <th scope="col" className="is-numeric">
                        Incremental comprovado
                      </th>
                      <th scope="col" className="is-numeric">
                        Recuperadas
                      </th>
                      <th scope="col" className="is-numeric">
                        Observações
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.amounts.map((row) => (
                      <tr key={row.currency ?? "unknown"}>
                        <td>
                          <strong>{row.currency ?? "Não informada"}</strong>
                        </td>
                        <td className="is-numeric">
                          {money(row.sale_value, row.currency) ?? (
                            <span className="cell-muted">Não informado</span>
                          )}
                        </td>
                        <td className="is-numeric">
                          {money(row.ares_influenced_value, row.currency) ?? (
                            <span className="cell-muted">Não informado</span>
                          )}
                        </td>
                        <td className="is-numeric">
                          {row.incremental_value === null ? (
                            <StatusBadge tone="neutral">
                              Não comprovado
                            </StatusBadge>
                          ) : (
                            money(row.incremental_value, row.currency)
                          )}
                        </td>
                        <td className="is-numeric">{row.recovered}</td>
                        <td className="is-numeric">
                          {row.observations}
                          {row.synthetic_observations ? (
                            <small className="cell-muted">
                              {" "}
                              ({row.synthetic_observations} sintética
                              {row.synthetic_observations === 1 ? "" : "s"})
                            </small>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <footer className="panel-footer">
              <span>{data.source}</span>
              <span>
                Consulta em {new Date(data.computed_at).toLocaleString("pt-BR")}
              </span>
            </footer>
          </section>
          <details className="panel">
            <summary>Definições e limitações</summary>
            <div className="panel-body">
              <ul className="definition-list">
                {data.definitions.map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
            </div>
          </details>
        </div>
      ) : null}
      <section className="panel console-section" aria-labelledby="impact-trail">
        <div className="panel-heading">
          <div>
            <h2 id="impact-trail">Trilha de intervenções</h2>
            <p>
              Cada linha liga a intervenção ao último resultado observado e à
              oportunidade de origem.
            </p>
          </div>
        </div>
        {page.isPending ? (
          <div className="panel-body">
            <Skeleton className="h-24 w-full" />
          </div>
        ) : null}
        {page.error ? (
          <div className="panel-body">
            <p className="inline-alert" role="alert">
              {page.error.message}
            </p>
          </div>
        ) : null}
        {!page.isError && page.data ? (
          <>
            {!page.data.items.length ? (
              <p className="data-empty">
                Nenhuma intervenção aberta neste período. As intervenções surgem
                no fluxo de recomendação e decisão.
              </p>
            ) : (
              <div
                className="data-table"
                role="region"
                aria-label="Trilha de intervenções, tabela rolável"
                tabIndex={0}
              >
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Intervenção</th>
                      <th scope="col">Estado</th>
                      <th scope="col">Resultado</th>
                      <th scope="col" className="is-numeric">
                        Valor
                      </th>
                      <th scope="col">Aberta em</th>
                      <th scope="col">Observado em</th>
                      <th scope="col">
                        <span className="sr-only">Oportunidade</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.data.items.map((row) => {
                      const status = interventionStatus[row.status] ?? {
                        tone: "neutral" as const,
                        label: row.status,
                      };
                      return (
                        <tr key={row.intervention_id}>
                          <td>
                            <div className="cell-stack">
                              <strong className="cell-mono">
                                {shortId(row.intervention_id)}
                              </strong>
                              <small title={row.correlation_id}>
                                corr. {shortId(row.correlation_id)}
                              </small>
                            </div>
                          </td>
                          <td>
                            <StatusBadge tone={status.tone}>
                              {status.label}
                            </StatusBadge>
                          </td>
                          <td>
                            <Result row={row} />
                          </td>
                          <td className="is-numeric">
                            {money(row.sale_value, row.currency) ?? (
                              <span className="cell-muted">—</span>
                            )}
                          </td>
                          <td>{when(row.created_at)}</td>
                          <td>
                            {when(row.observed_at) ?? (
                              <span className="cell-muted">—</span>
                            )}
                          </td>
                          <td>
                            <div className="cell-actions">
                              <Button asChild size="sm" variant="outline">
                                <Link
                                  to={`/opportunities/${row.opportunity_id}`}
                                >
                                  Abrir oportunidade{" "}
                                  <ArrowSquareOutIcon aria-hidden />
                                </Link>
                              </Button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <footer className="panel-footer">
              <span>
                {page.data.items.length} intervenç
                {page.data.items.length === 1 ? "ão" : "ões"} nesta página
              </span>
              <span className="pager">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!cursor}
                  onClick={() => setCursor(null)}
                >
                  Início
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!page.data.next_cursor}
                  onClick={() => setCursor(page.data?.next_cursor ?? null)}
                >
                  Próxima página
                </Button>
              </span>
            </footer>
          </>
        ) : null}
      </section>
    </main>
  );
}
