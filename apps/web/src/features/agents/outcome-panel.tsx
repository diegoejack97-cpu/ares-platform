import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/auth-context";
import {
  outcomeOpportunity,
  outcomeStart,
  outcomeFeedback,
  outcomeEpisode,
  outcomeMetrics,
  memoryConfiguration,
} from "./intelligence-api";
import "./commercial.css";
import "./memory.css";

export function OutcomePanel({ opportunityId }: { opportunityId: string }) {
  const { session } = useAuth();
  const client = useQueryClient();
  const identity = [
    session.user.id,
    session.user.app_metadata.active_tenant_id,
  ];
  const query = useQuery({
    queryKey: ["outcome", ...identity, opportunityId],
    queryFn: () => outcomeOpportunity(opportunityId),
    retry: false,
    refetchInterval: (q) =>
      ["queued", "running"].includes(q.state.data?.state ?? "") ? 5000 : false,
  });
  const config = useQuery({
    queryKey: ["memory-config", ...identity],
    queryFn: memoryConfiguration,
    retry: false,
  });
  const [reason, setReason] = useState("");
  const [rating, setRating] = useState<"helpful" | "unhelpful">("helpful");
  const [mode, setMode] = useState<"feedback" | "episode">("feedback");
  const mutation = useMutation({
    mutationFn: async () => {
      const evaluation = query.data?.evaluation?.id;
      if (!evaluation) throw new Error("Avaliação ainda indisponível.");
      return mode === "episode"
        ? outcomeEpisode(evaluation, reason)
        : outcomeFeedback(evaluation, { rating, rationale: reason });
    },
  });
  const start = useMutation({
    mutationFn: () => {
      const id = query.data?.chain?.intervention_id;
      if (!id) throw new Error("Intervenção ausente.");
      return outcomeStart(id);
    },
    onSuccess: () => void client.invalidateQueries({ queryKey: ["outcome"] }),
  });
  const data = query.data;
  const explanation = data?.evaluation?.explanation_json;
  const readOnly = session.user.app_metadata.role === "auditor";
  return (
    <section
      className="panel commercial-panel"
      aria-label="Avaliação de resultados"
    >
      <header>
        <div>
          <span className="eyebrow">CICLO DE EVIDÊNCIAS</span>
          <h2>Avaliação de resultados</h2>
          <p>
            Resultado observado, janela de análise e próximos passos para
            revisão humana.
          </p>
        </div>
      </header>
      {query.isPending ? (
        <p role="status">Carregando resultados…</p>
      ) : query.isError ? (
        <p role="alert">
          Não foi possível consultar a avaliação.{" "}
          <Button onClick={() => void query.refetch()}>Tentar novamente</Button>
        </p>
      ) : data?.state === "no_intervention" ? (
        <p>Nenhuma intervenção registrada nesta oportunidade.</p>
      ) : (
        <>
          <p>
            {
              (
                {
                  pending:
                    "Aguardando resultado observado. Não equivale a resultado zero.",
                  queued: "Avaliação na fila.",
                  running: "Agente avaliando as evidências…",
                  ready: "Avaliação concluída.",
                  degraded:
                    "Leitura por regras; interpretação por IA indisponível.",
                  not_requested:
                    "Resultado registrado; avaliação ainda não solicitada.",
                  failed: "Não foi possível concluir a avaliação.",
                } as Record<string, string>
              )[data?.state ?? ""]
            }
          </p>
          {data?.chain ? (
            <dl className="outcome-facts">
              <div>
                <dt>Resultado</dt>
                <dd>
                  {data.chain.outcome?.result_type ?? "Ainda não observado"}
                </dd>
              </div>
              <div>
                <dt>Janela de observação</dt>
                <dd>
                  {new Date(data.chain.window.start).toLocaleString("pt-BR")} —{" "}
                  {new Date(data.chain.window.end).toLocaleString("pt-BR")}
                </dd>
              </div>
              <div>
                <dt>Intervenções concorrentes</dt>
                <dd>{data.chain.concurrent_interventions}</dd>
              </div>
              <div>
                <dt>Registro tardio</dt>
                <dd>
                  {data.chain.late_outcome
                    ? "Sim; revisar a janela"
                    : "Não identificado"}
                </dd>
              </div>
            </dl>
          ) : null}
          {explanation ? (
            <>
              <p>{explanation.summary}</p>
              <ul>
                {explanation.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <h3>Próximos passos sugeridos</h3>
              <ul>
                {explanation.next_steps.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          ) : null}
          {!readOnly &&
          config.data?.configuration.outcomes_enabled &&
          data?.chain?.outcome &&
          !["queued", "running", "ready", "degraded"].includes(data.state) ? (
            <Button disabled={start.isPending} onClick={() => start.mutate()}>
              Solicitar avaliação
            </Button>
          ) : null}
          {data?.evaluation && !readOnly ? (
            <details className="memory-settings">
              <summary>Registrar opinião ou episódio verificado</summary>
              <form
                className="commercial-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  mutation.mutate();
                }}
              >
                <fieldset disabled={mutation.isPending}>
                  <legend>Feedback não altera fatos nem políticas</legend>
                  <label>
                    Tipo
                    <select
                      value={mode}
                      onChange={(e) =>
                        setMode(e.target.value as "feedback" | "episode")
                      }
                    >
                      <option value="feedback">Opinião do usuário</option>
                      {config.data?.can_configure &&
                      config.data.configuration.episodes_enabled &&
                      data.chain?.outcome ? (
                        <option value="episode">
                          Salvar fatos observados na memória
                        </option>
                      ) : null}
                    </select>
                  </label>
                  <label>
                    Avaliação
                    <select
                      value={rating}
                      onChange={(e) =>
                        setRating(e.target.value as "helpful" | "unhelpful")
                      }
                    >
                      <option value="helpful">Útil</option>
                      <option value="unhelpful">Precisa melhorar</option>
                    </select>
                  </label>
                  <label>
                    Justificativa
                    <input
                      required
                      minLength={8}
                      maxLength={300}
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                    />
                  </label>
                  <Button type="submit">Registrar</Button>
                </fieldset>
              </form>
            </details>
          ) : null}
          {mutation.isSuccess ? <p role="status">Registro salvo.</p> : null}
          {mutation.isError || start.isError ? (
            <p role="alert">
              {mutation.error?.message ?? start.error?.message}
            </p>
          ) : null}
          <details className="memory-settings">
            <summary>Referências da cadeia</summary>
            <p>Intervenção: {data?.chain?.intervention_id}</p>
            <p>Antes: {data?.chain?.state_before_ref}</p>
            <p>Depois: {data?.chain?.state_after_ref ?? "Pendente"}</p>
            <p>
              Fonte: Journal, recomendações, decisões, execução e outcomes.
              Atualização:{" "}
              {data?.evaluation?.finished_at
                ? new Date(data.evaluation.finished_at).toLocaleString("pt-BR")
                : "Avaliação ainda pendente"}
              .
            </p>
          </details>
        </>
      )}
      <footer>
        Associação observada não comprova causalidade. Valores financeiros e
        método de atribuição continuam no relatório Impacto ARES.
      </footer>
    </section>
  );
}

export function OutcomeMetricsPanel({ days }: { days: number }) {
  const { session } = useAuth();
  const query = useQuery({
    queryKey: [
      "outcome-metrics",
      session.user.id,
      session.user.app_metadata.active_tenant_id,
      days,
    ],
    queryFn: () => outcomeMetrics(days),
    retry: false,
  });
  const data = query.data;
  return (
    <section
      className="panel commercial-panel"
      aria-label="Indicadores das intervenções"
    >
      <header>
        <div>
          <span className="eyebrow">RESULTADOS OBSERVADOS</span>
          <h2>Ciclo das intervenções</h2>
          <p>
            Período: {days} dias. Fonte: recomendações, decisões, execuções e
            outcomes.
          </p>
        </div>
      </header>
      {query.isPending ? (
        <p role="status">Calculando indicadores…</p>
      ) : query.isError ? (
        <p role="alert">
          Indicadores indisponíveis.{" "}
          <Button onClick={() => void query.refetch()}>Tentar novamente</Button>
        </p>
      ) : data ? (
        <>
          <p>
            {data.interventions} intervenções · {data.outcomes_observed} com
            resultado · {data.pending} pendentes.
          </p>
          <dl className="outcome-facts">
            {[
              ["Adesão", data.adoption],
              ["Rejeição", data.rejection],
              ["Falha de execução", data.execution_failure],
              ["Mudança de estado", data.observed_state_change],
              ["Risco encerrado no Core", data.risk_resolution],
            ].map(([label, metric]) =>
              typeof metric === "object" ? (
                <div key={String(label)}>
                  <dt>{String(label)}</dt>
                  <dd>
                    {metric.numerator} / {metric.denominator}
                  </dd>
                  <small>{metric.definition}</small>
                </div>
              ) : null,
            )}
          </dl>
          <p>{data.response_definition}</p>
          <footer>
            {data.coverage} · Consultado em{" "}
            {new Date(query.dataUpdatedAt).toLocaleString("pt-BR")} · Sem
            conclusão causal.
          </footer>
        </>
      ) : null}
    </section>
  );
}
