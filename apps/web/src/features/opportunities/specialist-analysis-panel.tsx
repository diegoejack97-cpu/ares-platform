import { DetectiveIcon } from "@phosphor-icons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef } from "react";

import { Button } from "@/components/ui/button";
import {
  getOpportunityContext,
  getSpecialistAnalysis,
  startSpecialistAnalysis,
} from "./api";
import { dateTime } from "./format";
import "./specialist-analysis.css";

const states: Record<string, string> = {
  disabled: "Análise especializada desativada para esta empresa.",
  capacity_missing: "O plano precisa permitir dois agentes para esta análise.",
  not_requested: "Nenhuma análise especializada foi solicitada.",
  queued: "Análise na fila. As evidências continuam disponíveis abaixo.",
  running: "Os agentes estão analisando as evidências.",
  stale: "Os dados mudaram ou a análise venceu. Solicite uma nova análise.",
  degraded: "IA indisponível. Use as evidências e a revisão humana.",
  failed: "A análise falhou. O Radar e as evidências continuam disponíveis.",
  blocked: "A análise foi bloqueada pelos controles de acesso ou de qualidade.",
  cancelled: "Análise cancelada.",
  human_review:
    "A triagem indicou revisão humana; não há diagnóstico validado.",
};
const urgency: Record<string, string> = {
  low: "Baixa",
  normal: "Normal",
  high: "Alta",
  critical: "Crítica",
};
const fields: Record<string, string> = {
  score: "Score do Core",
  priority: "Prioridade do Core",
  title: "Negócio",
  value: "Valor salvo",
  currency: "Moeda",
  state: "Estado",
  signal_type: "Sinal",
  severity: "Severidade",
  sla_at: "Prazo de SLA",
  owner_user_id: "Responsável",
  canonical_stage: "Etapa",
};

export function SpecialistAnalysisPanel({
  opportunityId,
}: {
  opportunityId: string;
}) {
  const command = useRef<Parameters<typeof startSpecialistAnalysis>[0] | null>(
    null,
  );
  const analysis = useQuery({
    queryKey: ["specialist-analysis", opportunityId],
    queryFn: () => getSpecialistAnalysis(opportunityId),
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.state ?? "")
        ? 3000
        : 30000,
  });
  const start = useMutation({
    mutationFn: async () => {
      if (!command.current) {
        const context = await getOpportunityContext(opportunityId);
        command.current = {
          opportunity_id: opportunityId,
          context_ref: context.context_ref,
          idempotency_key: crypto.randomUUID(),
        };
      }
      return startSpecialistAnalysis(command.current);
    },
    onSuccess: async () => {
      command.current = null;
      await analysis.refetch();
    },
  });
  const data = analysis.data;
  const pending =
    start.isPending || ["queued", "running"].includes(data?.state ?? "");
  return (
    <section
      className="panel detail-section specialist-analysis"
      aria-labelledby="specialist-analysis-title"
    >
      <div className="panel-heading">
        <div>
          <h2 id="specialist-analysis-title">Triagem e diagnóstico</h2>
          <p>
            Interpretação das evidências · prioridade final definida pelo Core
          </p>
        </div>
        <DetectiveIcon size={20} aria-hidden />
      </div>
      <div className="specialist-analysis-body">
        {analysis.isPending ? (
          <p role="status">Carregando estado da análise…</p>
        ) : null}
        {analysis.isError ? (
          <div role="alert">
            <p>
              Não foi possível atualizar a análise. As evidências da
              oportunidade continuam disponíveis.
            </p>
            <Button variant="outline" onClick={() => void analysis.refetch()}>
              Tentar novamente
            </Button>
          </div>
        ) : null}
        {!analysis.isError && data?.state !== "ready" ? (
          <p role="status">{states[data?.state ?? ""]}</p>
        ) : null}
        {!analysis.isError && data?.can_request ? (
          <Button
            variant="outline"
            disabled={pending}
            onClick={() => start.mutate()}
          >
            {pending
              ? "Análise em andamento"
              : data.state === "ready"
                ? "Conferir análise atual"
                : start.isError
                  ? "Repetir solicitação"
                  : "Analisar evidências"}
          </Button>
        ) : null}
        {start.isError ? (
          <p role="alert">
            Não foi possível solicitar a análise ({start.error.message}).
            Repetir preserva o mesmo pedido.
          </p>
        ) : null}
        {!analysis.isError &&
        data?.state === "ready" &&
        data.triage &&
        data.diagnosis ? (
          <>
            <div>
              <h3>Triagem</h3>
              <p>{data.triage.summary}</p>
              <span className="specialist-urgency">
                Urgência proposta:{" "}
                {urgency[data.triage.proposed_urgency] ??
                  data.triage.proposed_urgency}
              </span>
            </div>
            <div>
              <h3>Diagnóstico</h3>
              <p>{data.diagnosis.summary}</p>
            </div>
            <div>
              <h3>Fatos conferidos no contexto</h3>
              {data.diagnosis.facts.length ? (
                <dl>
                  {data.diagnosis.facts.map((fact, i) => (
                    <div key={`${fact.path}-${i}`}>
                      <dt>
                        {fields[fact.path.split("/").at(-1) ?? ""] ??
                          "Dado registrado"}
                      </dt>
                      <dd>{fact.value}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p>Sem fatos estruturados suficientes para uma conclusão.</p>
              )}
            </div>
            {data.diagnosis.hypotheses.length ? (
              <div>
                <h3>Hipóteses — precisam de confirmação</h3>
                {data.diagnosis.hypotheses.map((hypothesis, i) => (
                  <div className="specialist-hypothesis" key={i}>
                    <p>{hypothesis.explanation}</p>
                    <small>
                      {hypothesis.supporting_refs.length} evidências favoráveis
                      · {hypothesis.contrary_refs.length} contrárias
                    </small>
                    {hypothesis.missing_information.length ? (
                      <ul>
                        {hypothesis.missing_information.map((item, j) => (
                          <li key={j}>{item}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}
            {data.diagnosis.needs_human_review ? (
              <p>Revisão humana necessária antes de decidir.</p>
            ) : null}
            {[...data.triage.limitations, ...data.diagnosis.limitations]
              .length ? (
              <div>
                <h3>Limitações</h3>
                <ul>
                  {[
                    ...new Set([
                      ...data.triage.limitations,
                      ...data.diagnosis.limitations,
                    ]),
                  ].map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            <details>
              <summary>Referências da análise</summary>
              <ul>
                {[
                  ...new Set([
                    ...data.triage.evidence_refs,
                    ...data.diagnosis.hypotheses.flatMap((hypothesis) => [
                      ...hypothesis.supporting_refs,
                      ...hypothesis.contrary_refs,
                    ]),
                  ]),
                ].map((ref) => (
                  <li key={ref}>
                    <code>{ref}</code>
                  </li>
                ))}
              </ul>
            </details>
          </>
        ) : null}
        {data ? (
          <small className="specialist-source">
            Fonte: {data.source}
            {data.valid_until
              ? ` · Validade: ${dateTime(data.valid_until)}`
              : ""}
            {data.truncated ? " · Contexto com cortes declarados" : ""}
          </small>
        ) : null}
      </div>
    </section>
  );
}
