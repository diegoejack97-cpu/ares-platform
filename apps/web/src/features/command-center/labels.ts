import type { AresThemeTokens } from "@/charts/aresTheme";
import { ordinalRamp, shade, tint } from "@/charts/aresTheme";

export const stateLabels: Record<string, string> = {
  detected: "Detectadas",
  qualifying: "Em qualificação",
  qualified: "Qualificada",
  prioritized: "Priorizadas",
  awaiting_decision: "Aguardando decisão",
  authorized: "Autorizadas",
  executing: "Em execução",
  observing: "Em observação",
  closed: "Encerradas",
};
export const reasonLabels: Record<string, string> = {
  first_signal_detected: "Primeiro sinal detectado",
  deterministic_score_available: "Score determinístico calculado",
  recommendation_generated: "Recomendação gerada",
  human_approval: "Aprovação humana",
  policy_allow_low_risk: "Política: baixo risco, liberado",
  worker_claimed_action: "Worker assumiu a ação",
  crm_action_succeeded: "Ação concluída no CRM",
};
export const actorLabels: Record<string, string> = {
  human: "Pessoa",
  ares_agent: "Agente ARES",
  system: "Sistema",
  external_system: "Sistema externo",
};
export const urgencyLabels: Record<string, string> = {
  critical: "Crítica",
  high: "Alta",
  normal: "Normal",
  low: "Baixa",
};
export const actionKindLabels: Record<string, string> = {
  create_task: "Criar tarefa",
  add_note: "Adicionar nota",
  update_stage: "Mover etapa",
};
export const connectionStatusLabels: Record<string, string> = {
  configured: "Configurada",
  healthy: "Saudável",
  degraded: "Degradada",
  revoked: "Revogada",
};
export const decisionLabels: Record<string, string> = {
  approved: "Aprovada",
  rejected: "Rejeitada",
  edited: "Editada",
};
export const actionStatusLabels: Record<string, string> = {
  succeeded: "Ação executada",
  failed: "Ação falhou",
};
export const roleWords: Record<string, string> = {
  admin: "admin",
  manager: "gestor",
  seller: "vendedor",
  auditor: "auditor",
};

// Same arrays as radar-intelligence-charts.tsx; duplicated so the two screens
// stay independently readable. Heatmap rows run top to bottom.
export const WEEKDAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
export const HOUR_BANDS = ["18–24h", "12–18h", "6–12h", "0–6h"];

/**
 * Severity picks the hue family; order of appearance within a family picks the
 * step, so two severity-5 signals never share a colour.
 */
export function signalTones(
  types: Array<{ signal_type: string; severity: number }>,
  tokens: AresThemeTokens,
): Record<string, string> {
  const families: Record<number, string[]> = {
    5: [tokens.brasa, tokens.ambar, tokens.lilas, shade(tokens.brasa, 0.35)],
    4: [tokens.aco, shade(tokens.aco, 0.35), tokens.jade],
    3: [tint(tokens.aco, 0.3)],
  };
  const used: Record<number, number> = {};
  const overflow: string[] = [];
  const tones: Record<string, string> = {};
  for (const type of types) {
    const family = families[type.severity] ?? [];
    const index = used[type.severity] ?? 0;
    used[type.severity] = index + 1;
    if (index < family.length) tones[type.signal_type] = family[index];
    else overflow.push(type.signal_type);
  }
  if (overflow.length) {
    const ramp = ordinalRamp(tokens.aco, overflow.length, tokens);
    overflow.forEach((key, i) => {
      tones[key] = ramp[i] ?? tokens.aco;
    });
  }
  return tones;
}
