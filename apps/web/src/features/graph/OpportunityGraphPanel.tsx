import { lazy, Suspense, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Freshness } from "@/components/live/freshness";
import { useAuth } from "@/features/auth/auth-context";
import { dateTime } from "@/features/opportunities/format";
import { getGraph, GraphError } from "./api";
import "./graph.css";

const GraphCanvas = lazy(() => import("./GraphCanvas"));
export function OpportunityGraphPanel({
  opportunityId,
}: {
  opportunityId: string;
}) {
  const [depth, setDepth] = useState(2);
  const [visual, setVisual] = useState(true);
  const { session } = useAuth();
  const query = useQuery({
    queryKey: [
      "opportunity-graph",
      session.user.id,
      session.user.app_metadata.active_tenant_id,
      opportunityId,
      depth,
    ],
    queryFn: ({ signal }) => getGraph(opportunityId, depth, signal),
    refetchInterval: 30_000,
    retry: (n, e) =>
      !(e instanceof GraphError && [401, 403, 404].includes(e.status)) && n < 1,
  });
  const denied =
    query.error instanceof GraphError &&
    [401, 403, 404].includes(query.error.status);
  const graph = denied ? undefined : query.data;
  const names = new Map(graph?.nodes.map((n) => [n.id, n.label]));
  return (
    <section
      className="panel detail-section evidence-graph"
      aria-labelledby="graph-title"
    >
      <div className="panel-heading">
        <div>
          <h2 id="graph-title">Relações com evidência</h2>
          <p>
            Vínculos atuais derivados do Journal. Não representam influência ou
            causalidade.
          </p>
        </div>
      </div>
      <div className="evidence-graph-controls">
        <label htmlFor="graph-depth">Profundidade</label>
        <select
          id="graph-depth"
          value={depth}
          onChange={(e) => setDepth(Number(e.target.value))}
        >
          <option value={1}>1 nível</option>
          <option value={2}>2 níveis</option>
        </select>
        <Button
          variant="outline"
          aria-pressed={visual}
          onClick={() => setVisual(!visual)}
        >
          {visual ? "Ocultar desenho" : "Mostrar desenho"}
        </Button>
        <Button
          variant="outline"
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
        >
          Atualizar grafo
        </Button>
      </div>
      {query.isPending ? (
        <Skeleton
          className="h-64 w-full"
          role="status"
          aria-label="Carregando relações"
        />
      ) : null}
      {query.isError ? (
        <div role="alert" className="evidence-graph-error">
          <p>{query.error.message}</p>
          {graph ? <p>Exibindo a última leitura recebida.</p> : null}
          {query.error instanceof GraphError && query.error.correlationId ? (
            <code>Correlação: {query.error.correlationId}</code>
          ) : null}
        </div>
      ) : null}
      {graph ? (
        <>
          <div className="evidence-graph-meta">
            <span>Fonte: {graph.source}</span>
            <span>Período: relações atuais</span>
            <Freshness timestamp={graph.freshness_at} />
          </div>
          {graph.edges.length ? (
            <>
              {visual ? (
                <Suspense fallback={<Skeleton className="h-64 w-full" />}>
                  <GraphCanvas graph={graph} />
                </Suspense>
              ) : null}
              <p className="evidence-graph-caption">
                {graph.edges.length} relações. O desenho pode ser arrastado; a
                lista abaixo apresenta as mesmas evidências.
              </p>
              <ul
                className="evidence-graph-list"
                aria-label="Relações e eventos de origem"
              >
                {graph.edges.map((e) => (
                  <li key={`${e.src_id}:${e.dst_id}:${e.evidence_event_id}`}>
                    <strong>
                      {names.get(e.src_id)} → {names.get(e.dst_id)}
                    </strong>
                    <details>
                      <summary>Ver evidência: {e.event_type}</summary>
                      <dl>
                        <div>
                          <dt>Evento</dt>
                          <dd>
                            <code>{e.evidence_event_id}</code>
                          </dd>
                        </div>
                        <div>
                          <dt>Data e fonte</dt>
                          <dd>
                            {dateTime(e.occurred_at)} | {e.source}
                          </dd>
                        </div>
                        <div>
                          <dt>Referência de destino</dt>
                          <dd>
                            <code>
                              {
                                graph.nodes.find((n) => n.id === e.dst_id)
                                  ?.external_ref
                              }
                            </code>
                          </dd>
                        </div>
                        <div>
                          <dt>Regra</dt>
                          <dd>{e.derivation_version}</dd>
                        </div>
                      </dl>
                    </details>
                  </li>
                ))}
              </ul>
              {graph.truncated ? (
                <p role="status">
                  Exibindo até {graph.edge_limit} relações. Reduza a
                  profundidade para inspecionar a origem.
                </p>
              ) : null}
            </>
          ) : (
            <div className="empty-state">
              <strong>Nenhuma relação comprovada disponível</strong>
              <p>
                As relações aparecem após o processamento de eventos com
                referências válidas do CRM. Atualize após a sincronização.
              </p>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
