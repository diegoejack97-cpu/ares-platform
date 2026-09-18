import { finiteNumber } from "@/lib/numbers";
export const signalLabels: Record<string, string> = {
  follow_up_overdue: "Follow-up vencido",
  proposal_stalled: "Proposta parada",
  missing_next_step: "Próximo passo ausente",
  unowned_deal: "Negócio sem responsável",
  high_value_at_risk: "Alto valor em risco",
  contact_inactive: "Contato inativo",
  close_date_at_risk: "Fechamento em risco",
  stage_regression: "Regressão de estágio",
};

export function money(value: unknown, currency = "BRL") {
  const numeric = finiteNumber(value);
  if (numeric === null) return "Valor não informado";
  try {
    return new Intl.NumberFormat("pt-BR", {
      style: "currency",
      currency,
    }).format(numeric);
  } catch {
    return `${numeric.toLocaleString("pt-BR")} (moeda não informada)`;
  }
}

export function dateTime(value: string | null) {
  if (!value || !Number.isFinite(Date.parse(value)))
    return "Data não informada";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

export function slaLabel(value: string | null, now = Date.now()) {
  if (!value || !Number.isFinite(Date.parse(value))) return "Sem SLA";
  const diff = new Date(value).getTime() - now;
  const overdue = diff < 0;
  const seconds = Math.floor(Math.abs(diff) / 1_000);
  const minutes = Math.floor(seconds / 60);
  const amount =
    minutes >= 60
      ? `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min`
      : `${minutes} min ${String(seconds % 60).padStart(2, "0")} s`;
  return overdue ? `Vencido há ${amount}` : `Vence em ${amount}`;
}

/** Priority 0 is the engine's highest urgency; the Radar and the Command Center share the words. */
export const priorityLabels = ["Crítica", "Alta", "Média", "Baixa"];
