import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { impactSummary, impactPage, downloadImpact } from "./api";
import "./impact.css";
const value = (amount: string | number | null, currency: string | null) =>
  amount === null
    ? "Não informado"
    : `${currency ?? "Moeda ausente"} ${Number(amount).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
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
  return (
    <main className="workspace impact-page">
      <header className="page-heading">
        <span className="eyebrow">RESULTADOS E EVIDÊNCIAS</span>
        <h1>Impacto ARES</h1>
        <p>
          Venda observada, influência e incrementalidade com definições
          explícitas.
        </p>
      </header>
      <div className="impact-actions">
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
        <Button
          variant="outline"
          onClick={() => {
            void summary.refetch();
            void page.refetch();
          }}
        >
          Atualizar relatório
        </Button>
        {(["csv", "pdf"] as const).map((format) => (
          <Button
            key={format}
            disabled={!data || download.isPending}
            onClick={() => download.mutate(format)}
          >
            Exportar {format.toUpperCase()}
          </Button>
        ))}
      </div>
      {download.isPending ? (
        <p role="status">Preparando exportação auditada…</p>
      ) : null}
      {download.error ? <p role="alert">{download.error.message}</p> : null}
      {summary.isPending ? <Skeleton className="h-64 w-full" /> : null}
      {summary.error ? <p role="alert">{summary.error.message}</p> : null}
      {data ? (
        <>
          {data.amounts.some((amount) => amount.synthetic_observations > 0) ? (
            <p role="status">
              Este relatório contém dados sintéticos de demonstração. Os valores
              não representam resultados comerciais reais.
            </p>
          ) : null}
          <p>
            {data.source} · Consulta:{" "}
            {new Date(data.computed_at).toLocaleString("pt-BR")}
          </p>
          <div className="impact-kpis">
            <section className="panel">
              <h2>Em risco</h2>
              <strong>{data.counts.at_risk}</strong>
              <p>Oportunidades ainda abertas</p>
            </section>
            <section className="panel">
              <h2>Trabalhadas</h2>
              <strong>{data.counts.worked}</strong>
              <p>Com intervenção no período</p>
            </section>
            <section className="panel">
              <h2>Custo de IA</h2>
              <strong>{value(data.ai_cost.cost_usd, "USD")}</strong>
              <p>
                {data.ai_cost.measured_runs} de {data.ai_cost.runs} execuções
                com custo medido
              </p>
            </section>
          </div>
          <section className="panel impact-section">
            <h2>Valores por moeda</h2>
            {!data.amounts.length ? (
              <p>
                Nenhum resultado observado no período. Registre o outcome com
                evidência no fluxo da oportunidade; ausência não representa
                receita zero.
              </p>
            ) : (
              <div
                className="impact-table"
                role="region"
                aria-label="Valores por moeda, tabela rolável"
                tabIndex={0}
              >
                <table>
                  <caption>
                    Último resultado observado por oportunidade no período
                  </caption>
                  <thead>
                    <tr>
                      <th>Moeda</th>
                      <th>Vendido</th>
                      <th>Influenciado</th>
                      <th>Incremental comprovado</th>
                      <th>Recuperadas</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.amounts.map((row) => (
                      <tr key={row.currency ?? "unknown"}>
                        <td>{row.currency ?? "Não informada"}</td>
                        <td>{value(row.sale_value, row.currency)}</td>
                        <td>
                          {value(row.ares_influenced_value, row.currency)}
                        </td>
                        <td>
                          {row.incremental_value === null
                            ? "Não comprovado"
                            : value(row.incremental_value, row.currency)}
                        </td>
                        <td>{row.recovered}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <details className="panel impact-section">
            <summary>Definições e limitações</summary>
            <ul>
              {data.definitions.map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ul>
          </details>
        </>
      ) : null}
      <section className="panel impact-section">
        <h2>Trilha de intervenções</h2>
        {page.isPending ? <Skeleton className="h-24 w-full" /> : null}
        {page.error ? <p role="alert">{page.error.message}</p> : null}
        {!page.isError && page.data ? (
          <>
            <ul className="impact-interventions">
              {page.data.items.map((row) => (
                <li key={row.intervention_id}>
                  <Link to={`/opportunities/${row.opportunity_id}`}>
                    Abrir oportunidade
                  </Link>
                  <span>
                    {row.status} ·{" "}
                    {row.result_type ?? "Resultado ainda não observado"}
                  </span>
                  <code>Intervenção: {row.intervention_id}</code>
                  <code>Correlação: {row.correlation_id}</code>
                </li>
              ))}
            </ul>
            {!page.data.items.length ? (
              <p>
                Nenhuma intervenção aberta neste período. As intervenções surgem
                no fluxo de recomendação e decisão.
              </p>
            ) : null}
            <div className="impact-actions">
              <Button
                variant="outline"
                disabled={!cursor}
                onClick={() => setCursor(null)}
              >
                Início
              </Button>
              <Button
                variant="outline"
                disabled={!page.data.next_cursor}
                onClick={() => setCursor(page.data?.next_cursor ?? null)}
              >
                Próxima página
              </Button>
            </div>
          </>
        ) : null}
      </section>
    </main>
  );
}
