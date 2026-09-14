import {
  ArrowLeftIcon,
  CheckCircleIcon,
  ClockIcon,
  LightningIcon,
  LinkIcon,
  ShieldCheckIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Freshness } from "@/components/live/freshness";
import { SlaCountdown } from "@/components/live/sla-countdown";
import { finiteNumber } from "@/lib/numbers";
import { RecommendationCard } from "@/features/decisions/recommendation-card";

import {
  decideRecommendation,
  generateRecommendation,
  getOpportunity,
  getOpportunityContext,
} from "./api";
import { dateTime, money, signalLabels } from "./format";
import { ScoreBar } from "./score-bar";
import { OpportunityGraphPanel } from "@/features/graph/OpportunityGraphPanel";

export function OpportunityDetailPage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["opportunity", id],
    queryFn: () => getOpportunity(id),
    enabled: Boolean(id),
    refetchInterval: 3_000,
  });
  const context = useQuery({
    queryKey: ["opportunity-context", id],
    queryFn: () => getOpportunityContext(id),
    enabled: Boolean(id),
  });
  const generate = useMutation({
    mutationFn: () => generateRecommendation(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["opportunity", id] });
      await queryClient.invalidateQueries({ queryKey: ["approvals"] });
    },
  });
  const decide = useMutation({
    mutationFn: (command: Parameters<typeof decideRecommendation>[1]) => {
      if (!detail.data?.recommendation)
        throw new Error("recommendation_missing");
      return decideRecommendation(detail.data.recommendation.id, command);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["opportunity", id] });
      await queryClient.invalidateQueries({ queryKey: ["approvals"] });
    },
  });

  if (detail.isLoading)
    return (
      <main className="workspace">
        <div className="detail-loading">
          <i />
          <i />
          <i />
        </div>
      </main>
    );
  if (!detail.data)
    return (
      <main className="workspace">
        <div className="empty-state">
          <strong>Oportunidade indisponível</strong>
          <span>
            {detail.error?.message ?? "O recurso não existe neste tenant."}
          </span>
          <Link to="/radar">Voltar ao Radar</Link>
          <Button variant="outline" onClick={() => void detail.refetch()}>
            Tentar novamente
          </Button>
        </div>
      </main>
    );
  const { opportunity, evidence, timeline, recommendation } = detail.data;

  return (
    <main className="workspace detail-page">
      <Link className="back-link" to="/radar">
        <ArrowLeftIcon aria-hidden /> Voltar ao Radar
      </Link>
      {detail.isError ? (
        <div className="route-status" role="alert">
          A leitura não pôde ser atualizada. Exibindo o último contexto
          recebido.
          <Button onClick={() => void detail.refetch()}>
            Tentar novamente
          </Button>
        </div>
      ) : null}
      <header className="detail-header">
        <div>
          <span className="eyebrow">
            Oportunidade · {opportunity.external_id}
          </span>
          <h1>{opportunity.title}</h1>
          <p>
            {opportunity.external_stage ?? "Sem estágio"} · aberta em{" "}
            {dateTime(opportunity.opened_at)}
          </p>
          <Freshness timestamp={detail.dataUpdatedAt} />
        </div>
        <div className="detail-score">
          <span>Score explicável</span>
          <ScoreBar
            score={opportunity.score}
            breakdown={opportunity.score_breakdown}
          />
          <small>{opportunity.score_version}</small>
        </div>
      </header>

      <section className="detail-meta" aria-label="Resumo da oportunidade">
        <div>
          <span>Valor do negócio</span>
          <strong>{money(opportunity.deal_value, opportunity.currency)}</strong>
          <small>Valor observado no CRM</small>
        </div>
        <div>
          <span>SLA</span>
          <strong>
            <SlaCountdown timestamp={opportunity.sla_at} />
          </strong>
          <small>{dateTime(opportunity.sla_at)}</small>
        </div>
        <div>
          <span>Estado</span>
          <strong>{opportunity.state}</strong>
          <small>versão {opportunity.version}</small>
        </div>
        <div>
          <span>Correlação</span>
          <code>{opportunity.correlation_id}</code>
          <small>cadeia auditável</small>
        </div>
      </section>

      <section className="detail-grid">
        <div className="detail-column">
          <section className="panel detail-section">
            <div className="panel-heading">
              <div>
                <h2>Por que agora</h2>
                <p>
                  {evidence.length} evidências produzidas por regras
                  determinísticas
                </p>
              </div>
              <ShieldCheckIcon aria-hidden />
            </div>
            <div className="evidence-list">
              {evidence.map((item) => (
                <a
                  key={item.id}
                  className="evidence-card"
                  href={`#event-${item.event_id}`}
                >
                  <span className="severity">S{item.severity}</span>
                  <div>
                    <strong>
                      {signalLabels[item.signal_type] ?? item.signal_type}
                    </strong>
                    <small>
                      {item.rule_id} · {item.rule_version}
                    </small>
                    <p>{JSON.stringify(item.evidence)}</p>
                  </div>
                  <LinkIcon aria-hidden />
                </a>
              ))}
            </div>
          </section>

          <OpportunityGraphPanel opportunityId={id} />

          <section className="panel detail-section">
            <div className="panel-heading">
              <div>
                <h2>Timeline auditável</h2>
                <p>Transições com ator, fonte e evento de evidência</p>
              </div>
              <ClockIcon aria-hidden />
            </div>
            <ol className="timeline">
              {timeline.map((entry) => (
                <li
                  key={entry.id}
                  id={
                    entry.evidence_event_id
                      ? `event-${entry.evidence_event_id}`
                      : undefined
                  }
                >
                  <span>
                    <CheckCircleIcon aria-hidden />
                  </span>
                  <div>
                    <strong>
                      {entry.from_state ?? "origem"} → {entry.to_state}
                    </strong>
                    <p>{entry.reason}</p>
                    <small>
                      {dateTime(entry.occurred_at)} · {entry.actor_type}/
                      {entry.actor_id} · {entry.source}
                    </small>
                  </div>
                </li>
              ))}
            </ol>
          </section>
        </div>

        <aside className="detail-column">
          <section className="panel detail-section score-breakdown">
            <div className="panel-heading">
              <div>
                <h2>Decomposição do score</h2>
                <p>Valores persistidos, não recalculados na interface</p>
              </div>
            </div>
            <dl>
              {Object.entries(opportunity.score_breakdown).map(
                ([key, part]) => (
                  <div key={key}>
                    <dt>{key.replaceAll("_", " ")}</dt>
                    <dd>
                      <strong>
                        {finiteNumber(part.value) === null
                          ? "Não informado"
                          : Math.round(part.value * 100)}
                      </strong>
                      <small>
                        peso{" "}
                        {finiteNumber(part.weight) === null
                          ? "não informado"
                          : `${Math.round(part.weight * 100)}%`}
                      </small>
                    </dd>
                  </div>
                ),
              )}
            </dl>
          </section>

          <section className="panel detail-section context-card">
            <div className="panel-heading">
              <div>
                <h2>Contexto da oportunidade</h2>
                <p>Memória e referências que sustentam a análise</p>
              </div>
            </div>
            {context.isLoading ? (
              <div className="context-loading">Carregando contexto…</div>
            ) : context.data ? (
              <dl>
                <div>
                  <dt>Context ref</dt>
                  <dd>
                    <code>{context.data.context_ref}</code>
                  </dd>
                </div>
                <div>
                  <dt>Tokens estimados</dt>
                  <dd>{context.data.token_estimate} / 2.500</dd>
                </div>
                <div>
                  <dt>Eventos citados</dt>
                  <dd>{context.data.included_event_count}</dd>
                </div>
                <div>
                  <dt>Hash</dt>
                  <dd>
                    <code>{context.data.content_hash.slice(0, 16)}…</code>
                  </dd>
                </div>
                <div>
                  <dt>Corte aplicado</dt>
                  <dd>
                    {context.data.truncated
                      ? `Sim (${context.data.omitted_event_count})`
                      : "Não"}
                  </dd>
                </div>
              </dl>
            ) : (
              <p className="context-error">
                Contexto indisponível. {context.error?.message}
              </p>
            )}
          </section>

          <section className="panel recommendation-panel">
            <div className="panel-heading">
              <div>
                <h2>Decisão e ação</h2>
                <p>Recomendado não significa executado</p>
              </div>
              <LightningIcon aria-hidden />
            </div>
            {generate.isError || decide.isError ? (
              <div className="decision-error" role="alert">
                <WarningCircleIcon aria-hidden />
                <span>{generate.error?.message ?? decide.error?.message}</span>
              </div>
            ) : null}
            {recommendation ? (
              <RecommendationCard
                recommendation={recommendation}
                pending={decide.isPending}
                onDecide={(command) => decide.mutate(command)}
              />
            ) : (
              <div className="recommendation-empty">
                <span>PRÓXIMA MELHOR AÇÃO</span>
                <h2>Recomendação ainda não gerada</h2>
                <p>
                  O ARES usa o snapshot auditável. Sem chave OpenAI, degrada
                  para regra determinística e mantém aprovação humana.
                </p>
                <Button
                  type="button"
                  disabled={generate.isPending}
                  onClick={() => generate.mutate()}
                >
                  <LightningIcon aria-hidden />
                  {generate.isPending ? "Gerando…" : "Gerar recomendação"}
                </Button>
              </div>
            )}
          </section>
        </aside>
      </section>
    </main>
  );
}
