import {
  ArrowsClockwiseIcon,
  CheckIcon,
  ClipboardTextIcon,
  NotePencilIcon,
  ProhibitIcon,
  ShieldCheckIcon,
  ShieldSlashIcon,
  ShieldWarningIcon,
} from "@phosphor-icons/react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useLiveClock } from "@/lib/live-clock";
import type {
  ActionDraft,
  Recommendation,
} from "@/features/opportunities/types";

interface RecommendationCardProps {
  recommendation: Recommendation;
  compact?: boolean;
  pending?: boolean;
  onDecide: (command: {
    verdict: "approved" | "edited" | "rejected";
    expected_version: number;
    edited_payload?: ActionDraft;
    reason?: string;
  }) => void;
}

const actionLabels = {
  create_task: "Criar tarefa no CRM",
  add_note: "Adicionar nota no CRM",
  update_stage: "Alterar estágio",
};

const actionIcons = {
  create_task: ClipboardTextIcon,
  add_note: NotePencilIcon,
  update_stage: ArrowsClockwiseIcon,
};

const urgencyLabels = {
  low: "Baixa",
  normal: "Normal",
  high: "Alta",
  critical: "Crítica",
};

const policyIcons = {
  allow: ShieldCheckIcon,
  require_approval: ShieldWarningIcon,
  deny: ShieldSlashIcon,
};

const policyLabels = {
  allow: "Permitida pela política",
  require_approval: "Revisão humana",
  deny: "Bloqueada pela política",
};

function editableField(action: ActionDraft): "title" | "body" | "stage" {
  if (action.action_kind === "create_task") return "title";
  if (action.action_kind === "add_note") return "body";
  return "stage";
}

export function RecommendationCard({
  recommendation,
  compact = false,
  pending = false,
  onDecide,
}: RecommendationCardProps) {
  const [editing, setEditing] = useState(false);
  const now = useLiveClock();
  const field = editableField(recommendation.recommended_action);
  const ActionIcon = actionIcons[recommendation.recommended_action.action_kind];
  const PolicyIcon = policyIcons[recommendation.policy_verdict];
  const [editedValue, setEditedValue] = useState(
    String(recommendation.recommended_action.payload[field] ?? ""),
  );
  const awaitingApproval =
    recommendation.status === "pending" &&
    recommendation.policy_verdict === "require_approval";
  const expiry = recommendation.approval_expires_at
    ? Date.parse(recommendation.approval_expires_at)
    : NaN;
  const expired = Number.isFinite(expiry) && expiry <= now;
  const canDecide =
    awaitingApproval &&
    recommendation.can_decide === true &&
    recommendation.approval_status === "pending" &&
    Number.isFinite(expiry) &&
    !expired;

  return (
    <article className={`decision-card${compact ? " compact" : ""}`}>
      <div className="decision-strip">
        <span className={`urgency urgency-${recommendation.urgency}`}>
          {urgencyLabels[recommendation.urgency]}
        </span>
        <span>
          {recommendation.generation_mode === "agno_openai"
            ? "Agno · OpenAI"
            : "Fallback determinístico"}
        </span>
        <code>v{recommendation.version}</code>
      </div>
      <div className="decision-body">
        <div className="decision-title">
          <div className="decision-title-main">
            <span className="decision-action-icon" aria-hidden="true">
              <ActionIcon size={19} weight="bold" />
            </span>
            <div>
              <span>Ação recomendada</span>
              <h3>
                {actionLabels[recommendation.recommended_action.action_kind]}
              </h3>
            </div>
          </div>
          <span
            className={`decision-policy policy-${recommendation.policy_verdict}`}
          >
            <PolicyIcon size={15} aria-hidden="true" />
            {policyLabels[recommendation.policy_verdict]}
          </span>
        </div>
        <p className="action-copy">
          {String(recommendation.recommended_action.payload[field] ?? "")}
        </p>
        <p className="decision-rationale">{recommendation.rationale}</p>

        {!compact && recommendation.alternatives.length > 0 && (
          <details className="decision-alternatives">
            <summary>Ver alternativa e trade-off</summary>
            {recommendation.alternatives.map((alternative) => (
              <div key={alternative.label}>
                <strong>{alternative.label}</strong>
                <span>{alternative.tradeoff}</span>
              </div>
            ))}
          </details>
        )}

        {recommendation.contraindication && (
          <div className="contraindication">
            <strong>Antes de aprovar</strong>
            <span>{recommendation.contraindication}</span>
          </div>
        )}

        <dl className="decision-audit">
          <div>
            <dt>Policy</dt>
            <dd>{recommendation.policy_verdict}</dd>
          </div>
          <div>
            <dt>Confiança</dt>
            <dd>{Math.round(recommendation.confidence * 100)}%</dd>
          </div>
          <div>
            <dt>Context ref</dt>
            <dd title={recommendation.context_ref}>
              {recommendation.context_ref.slice(0, 8)}…
            </dd>
          </div>
          <div>
            <dt>Execução</dt>
            <dd>{recommendation.action_status ?? "não autorizada"}</dd>
          </div>
        </dl>

        {awaitingApproval && !canDecide && (
          <p className="decision-rationale" role="status">
            {expired
              ? "Esta aprovação expirou. Atualize a consulta."
              : recommendation.approval_required_role === "manager"
                ? "Esta ação exige aprovação de um gestor ou administrador."
                : "Aprovação indisponível neste acesso. Atualize a consulta se sua permissão mudou."}
          </p>
        )}

        {editing && canDecide && (
          <form
            className="decision-edit"
            onSubmit={(event) => {
              event.preventDefault();
              onDecide({
                verdict: "edited",
                expected_version: recommendation.version,
                edited_payload: {
                  action_kind: recommendation.recommended_action.action_kind,
                  payload: {
                    ...recommendation.recommended_action.payload,
                    [field]: editedValue,
                  },
                },
                reason: "Ajuste humano antes da aprovação",
              });
            }}
          >
            <label htmlFor={`edit-${recommendation.id}`}>
              Conteúdo que será executado
            </label>
            <input
              id={`edit-${recommendation.id}`}
              value={editedValue}
              onChange={(event) => setEditedValue(event.target.value)}
              required
              autoFocus
            />
            <div>
              <Button type="submit" disabled={pending}>
                <CheckIcon aria-hidden /> Aprovar edição
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => setEditing(false)}
              >
                Cancelar
              </Button>
            </div>
          </form>
        )}

        {canDecide && !editing && (
          <div className="decision-actions" aria-label="Decisão humana">
            <Button
              type="button"
              disabled={pending}
              onClick={() =>
                onDecide({
                  verdict: "approved",
                  expected_version: recommendation.version,
                })
              }
            >
              <CheckIcon aria-hidden /> Aprovar
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => setEditing(true)}
            >
              <NotePencilIcon aria-hidden /> Editar antes
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() =>
                onDecide({
                  verdict: "rejected",
                  expected_version: recommendation.version,
                  reason: "Rejeitada pelo responsável",
                })
              }
            >
              <ProhibitIcon aria-hidden /> Rejeitar
            </Button>
          </div>
        )}
        {recommendation.executed_action && (
          <div className="executed-action">
            <span>Ação executada</span>
            <strong>
              {actionLabels[recommendation.executed_action.action_kind]}
            </strong>
            <small>Executor: tick-worker:m3.1 · fonte: FakeCRM</small>
          </div>
        )}
      </div>
    </article>
  );
}
